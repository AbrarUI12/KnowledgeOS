"""Unit tests for the T4.3 weighted RRF fusion module.

Every assertion is hand-computed from the RRF formula ``weight / (k0 + rank)`` with the default
config (k0 = 60, dense_weight = 0.55, lexical_weight = 0.45). The suite is written to exercise
every branch of ``reciprocal_rank_fusion`` (100% branch coverage) and to pin the ordering,
tie-breaking, dedupe, near-duplicate cap, per-document cap and continuity guarantees.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from pydantic import ValidationError

from app.rag.fusion import FusionConfig, reciprocal_rank_fusion
from app.rag.types import Candidate, RankedHit

# ---------------------------------------------------------------------------
# Deterministic fixture helpers
# ---------------------------------------------------------------------------


def make_hash(label: str) -> str:
    """A stable, valid 64-hex-char content hash for a label."""
    return hashlib.sha256(label.encode()).hexdigest()


def make_candidate(
    *,
    chunk_id: uuid.UUID,
    document_id: uuid.UUID,
    content_hash: str,
    ordinal: int = 1,
) -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version_id=uuid.UUID(int=0),
        knowledge_base_id=uuid.UUID(int=0),
        ordinal=ordinal,
        title=f"chunk-{int(chunk_id)}",
        content=f"content for chunk {int(chunk_id)}",
        content_hash=content_hash,
        token_count=10,
    )


def dense_hit(candidate: Candidate, rank: int, score: float = 1.0) -> RankedHit:
    return RankedHit(candidate=candidate, dense_rank=rank, dense_score=score)


def lexical_hit(candidate: Candidate, rank: int, score: float = 1.0) -> RankedHit:
    return RankedHit(candidate=candidate, lexical_rank=rank, lexical_score=score)


def uid(n: int) -> uuid.UUID:
    """Deterministic UUIDs whose integer value (and thus sort order) equals ``n``."""
    return uuid.UUID(int=n)


# ---------------------------------------------------------------------------
# Ordering & scoring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionOrderingAndScoring:
    def test_both_branches_sum_contributions(self) -> None:
        """A chunk returned by both branches at rank 1 sums both weighted terms."""
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        result = reciprocal_rank_fusion([dense_hit(cand, 1)], [lexical_hit(cand, 1)])
        assert len(result) == 1
        hit = result[0]
        assert hit.fused_score == pytest.approx(0.55 / 61 + 0.45 / 61)
        assert hit.dense_rank == 1
        assert hit.lexical_rank == 1

    def test_dense_only_has_single_contribution(self) -> None:
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        result = reciprocal_rank_fusion([dense_hit(cand, 1)], [])
        assert len(result) == 1
        hit = result[0]
        assert hit.fused_score == pytest.approx(0.55 / 61)
        assert hit.lexical_rank is None
        assert hit.lexical_score is None
        assert hit.dense_rank == 1

    def test_lexical_only_has_single_contribution(self) -> None:
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        result = reciprocal_rank_fusion([], [lexical_hit(cand, 1)])
        assert len(result) == 1
        hit = result[0]
        assert hit.fused_score == pytest.approx(0.45 / 61)
        assert hit.dense_rank is None
        assert hit.dense_score is None
        assert hit.lexical_rank == 1

    def test_both_branches_beat_single_branch(self) -> None:
        """X (both, rank 1) > Y (dense, rank 2) > Z (lexical, rank 2)."""
        x = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("x"))
        y = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("y"))
        z = make_candidate(chunk_id=uid(3), document_id=uid(102), content_hash=make_hash("z"))
        result = reciprocal_rank_fusion(
            [dense_hit(x, 1), dense_hit(y, 2)],
            [lexical_hit(x, 1), lexical_hit(z, 2)],
        )
        assert [h.chunk_id for h in result] == [uid(1), uid(2), uid(3)]
        assert result[0].fused_score == pytest.approx(0.55 / 61 + 0.45 / 61)
        assert result[1].fused_score == pytest.approx(0.55 / 62)
        assert result[2].fused_score == pytest.approx(0.45 / 62)

    def test_results_sorted_descending_by_fused_score(self) -> None:
        cands = [
            make_candidate(
                chunk_id=uid(i), document_id=uid(100 + i), content_hash=make_hash(str(i))
            )
            for i in range(1, 5)
        ]
        dense = [
            dense_hit(cands[2], 1),
            dense_hit(cands[0], 2),
            dense_hit(cands[3], 3),
            dense_hit(cands[1], 4),
        ]
        result = reciprocal_rank_fusion(dense, [])
        scores = [h.fused_score for h in result]
        assert scores == sorted(scores, reverse=True)
        assert [h.chunk_id for h in result] == [uid(3), uid(1), uid(4), uid(2)]

    def test_deterministic_tie_break_by_chunk_id(self) -> None:
        """Equal fused scores are ordered by ascending chunk id (a stable total order)."""
        x = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("x"))
        y = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("y"))
        # Both dense-only at rank 1 -> identical score 0.55/61.
        result = reciprocal_rank_fusion([dense_hit(x, 1), dense_hit(y, 1)], [])
        assert result[0].fused_score == pytest.approx(result[1].fused_score)
        assert [h.chunk_id for h in result] == [uid(1), uid(2)]

    def test_output_order_independent_of_input_order(self) -> None:
        """Reordering the inputs yields the same fused order."""
        a = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        b = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("b"))
        c = make_candidate(chunk_id=uid(3), document_id=uid(102), content_hash=make_hash("c"))
        first = reciprocal_rank_fusion([dense_hit(a, 1), dense_hit(b, 2)], [lexical_hit(c, 1)])
        second = reciprocal_rank_fusion([dense_hit(b, 2), dense_hit(a, 1)], [lexical_hit(c, 1)])
        assert [h.chunk_id for h in first] == [h.chunk_id for h in second]


# ---------------------------------------------------------------------------
# Dedupe by chunk id
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionDedupe:
    def test_chunk_in_both_branches_is_merged_once(self) -> None:
        """A chunk returned by both branches appears exactly once and keeps both ranks."""
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        result = reciprocal_rank_fusion(
            [dense_hit(cand, 2, score=0.9)], [lexical_hit(cand, 3, score=0.5)]
        )
        assert len(result) == 1
        hit = result[0]
        assert hit.dense_rank == 2
        assert hit.dense_score == pytest.approx(0.9)
        assert hit.lexical_rank == 3
        assert hit.lexical_score == pytest.approx(0.5)
        assert hit.fused_score == pytest.approx(0.55 / 62 + 0.45 / 63)

    def test_dense_only_hit_has_no_lexical_fields(self) -> None:
        """A chunk seen only in the dense branch never inherits the other branch's fields."""
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        result = reciprocal_rank_fusion([dense_hit(cand, 1)], [])
        hit = result[0]
        assert hit.dense_rank == 1
        assert hit.lexical_rank is None
        assert hit.lexical_score is None


# ---------------------------------------------------------------------------
# Near-duplicate cap by content hash
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionNearDuplicateCap:
    def test_same_content_hash_keeps_only_highest_scored(self) -> None:
        """Two distinct chunks with identical content_hash: only the top scorer survives."""
        # Different documents so the per-document cap (3) cannot interfere.
        a = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("dup"))
        b = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("dup"))
        result = reciprocal_rank_fusion([dense_hit(a, 1), dense_hit(b, 2)], [])
        assert [h.chunk_id for h in result] == [uid(1)]
        assert result[0].fused_score == pytest.approx(0.55 / 61)

    def test_distinct_content_hashes_all_survive(self) -> None:
        """Distinct content hashes on distinct documents are never dropped by the hash cap."""
        a = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        b = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("b"))
        result = reciprocal_rank_fusion([dense_hit(a, 1), dense_hit(b, 2)], [])
        assert [h.chunk_id for h in result] == [uid(1), uid(2)]

    def test_custom_max_per_content_hash_allows_more(self) -> None:
        """Raising max_per_content_hash keeps near-duplicates that the default would drop."""
        a = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("dup"))
        b = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("dup"))
        cfg = FusionConfig(max_per_content_hash=2)
        result = reciprocal_rank_fusion([dense_hit(a, 1), dense_hit(b, 2)], [], config=cfg)
        assert [h.chunk_id for h in result] == [uid(1), uid(2)]


# ---------------------------------------------------------------------------
# Per-document cap & continuity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionPerDocumentCap:
    def _same_doc_dense(self, n: int) -> list[RankedHit]:
        """n ordinally-contiguous chunks from one document, ranked in ordinal order."""
        doc = uid(100)
        return [
            dense_hit(
                make_candidate(
                    chunk_id=uid(i),
                    document_id=doc,
                    content_hash=make_hash(f"ch{i}"),
                    ordinal=i,
                ),
                rank=i,
            )
            for i in range(1, n + 1)
        ]

    def test_default_cap_keeps_top_three_contiguous(self) -> None:
        """Default max_per_document=3 keeps the three highest-scored (contiguous) chunks."""
        result = reciprocal_rank_fusion(self._same_doc_dense(5), [])
        assert len(result) == 3
        assert [h.chunk_id for h in result] == [uid(1), uid(2), uid(3)]
        assert [h.candidate.ordinal for h in result] == [1, 2, 3]
        # The fourth chunk is dropped even though it is a distinct content hash.
        assert uid(4) not in {h.chunk_id for h in result}

    def test_surviving_chunks_are_ordinally_contiguous(self) -> None:
        """The per-document survivors form a contiguous ordinal run (no gaps)."""
        result = reciprocal_rank_fusion(self._same_doc_dense(5), [])
        ordinals = [h.candidate.ordinal for h in result]
        assert ordinals == list(range(ordinals[0], ordinals[0] + len(ordinals)))

    def test_custom_max_per_document(self) -> None:
        """A tighter cap keeps fewer chunks from the same document."""
        cfg = FusionConfig(max_per_document=2)
        result = reciprocal_rank_fusion(self._same_doc_dense(5), [], config=cfg)
        assert [h.chunk_id for h in result] == [uid(1), uid(2)]

    def test_cap_applies_per_document_not_globally(self) -> None:
        """Two documents each keep their own top chunks; the cap is per-document."""
        doc_a, doc_b = uid(100), uid(200)
        dense = [
            dense_hit(
                make_candidate(
                    chunk_id=uid(i), document_id=doc_a, content_hash=make_hash(f"a{i}"), ordinal=i
                ),
                rank=i,
            )
            for i in range(1, 4)
        ] + [
            dense_hit(
                make_candidate(
                    chunk_id=uid(10 + i),
                    document_id=doc_b,
                    content_hash=make_hash(f"b{i}"),
                    ordinal=i,
                ),
                rank=i,
            )
            for i in range(1, 4)
        ]
        result = reciprocal_rank_fusion(dense, [])
        # Default cap 3: all three from each of the two documents survive.
        assert len(result) == 6
        by_doc = {h.candidate.document_id for h in result}
        assert by_doc == {doc_a, doc_b}
        from_doc_a = sorted(int(h.chunk_id) for h in result if h.candidate.document_id == doc_a)
        assert from_doc_a == [1, 2, 3]


# ---------------------------------------------------------------------------
# Combined caps
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionCombinedCaps:
    def test_hash_cap_and_document_cap_interact(self) -> None:
        """Within one document, the hash cap drops duplicates before the document cap counts."""
        doc = uid(100)
        hits = [
            dense_hit(
                make_candidate(
                    chunk_id=uid(1), document_id=doc, content_hash=make_hash("dup"), ordinal=1
                ),
                rank=1,
            ),
            dense_hit(
                make_candidate(
                    chunk_id=uid(2), document_id=doc, content_hash=make_hash("dup"), ordinal=2
                ),
                rank=2,
            ),
            dense_hit(
                make_candidate(
                    chunk_id=uid(3), document_id=doc, content_hash=make_hash("c3"), ordinal=3
                ),
                rank=3,
            ),
            dense_hit(
                make_candidate(
                    chunk_id=uid(4), document_id=doc, content_hash=make_hash("c4"), ordinal=4
                ),
                rank=4,
            ),
            dense_hit(
                make_candidate(
                    chunk_id=uid(5), document_id=doc, content_hash=make_hash("c5"), ordinal=5
                ),
                rank=5,
            ),
        ]
        # Scores: uid1 (0.55/61) > uid2 (0.55/62) > uid3 (0.55/63) > uid4 > uid5.
        # hash cap drops uid2 (dup of uid1). Remaining order: uid1, uid3, uid4, uid5.
        # document cap 3 keeps uid1, uid3, uid4.
        result = reciprocal_rank_fusion(hits, [])
        assert [h.chunk_id for h in result] == [uid(1), uid(3), uid(4)]


# ---------------------------------------------------------------------------
# Purity, determinism & edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionPurityAndEdges:
    def test_inputs_are_not_mutated(self) -> None:
        """Fusion never mutates the caller's RankedHits."""
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        dense_in = [dense_hit(cand, 1)]
        lexical_in = [lexical_hit(cand, 1)]
        reciprocal_rank_fusion(dense_in, lexical_in)
        assert dense_in[0].fused_score is None
        assert dense_in[0].lexical_rank is None
        assert lexical_in[0].fused_score is None
        assert lexical_in[0].dense_rank is None

    def test_result_hits_carry_fused_score(self) -> None:
        cand = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        result = reciprocal_rank_fusion([dense_hit(cand, 1)], [])
        assert result[0].fused_score is not None
        assert result[0].fused_score == pytest.approx(0.55 / 61)

    def test_both_branches_empty_returns_empty(self) -> None:
        assert reciprocal_rank_fusion([], []) == []

    def test_deterministic_across_calls(self) -> None:
        a = make_candidate(chunk_id=uid(1), document_id=uid(100), content_hash=make_hash("a"))
        b = make_candidate(chunk_id=uid(2), document_id=uid(101), content_hash=make_hash("b"))
        call1 = reciprocal_rank_fusion([dense_hit(a, 1)], [lexical_hit(b, 1)])
        call2 = reciprocal_rank_fusion([dense_hit(a, 1)], [lexical_hit(b, 1)])
        assert [h.chunk_id for h in call1] == [h.chunk_id for h in call2]
        assert [h.fused_score for h in call1] == [h.fused_score for h in call2]


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFusionConfig:
    def test_defaults_match_baseline(self) -> None:
        cfg = FusionConfig()
        assert cfg.k0 == 60.0
        assert cfg.dense_weight == pytest.approx(0.55)
        assert cfg.lexical_weight == pytest.approx(0.45)
        assert cfg.max_per_document == 3
        assert cfg.max_per_content_hash == 1

    def test_k0_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            FusionConfig(k0=0)

    def test_weights_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            FusionConfig(dense_weight=-0.1)

    def test_max_per_document_at_least_one(self) -> None:
        with pytest.raises(ValidationError):
            FusionConfig(max_per_document=0)

    def test_max_per_content_hash_at_least_one(self) -> None:
        with pytest.raises(ValidationError):
            FusionConfig(max_per_content_hash=0)

    def test_config_is_frozen(self) -> None:
        cfg = FusionConfig()
        with pytest.raises(ValidationError):
            cfg.k0 = 10  # type: ignore[misc]
