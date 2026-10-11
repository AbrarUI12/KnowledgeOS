"""Weighted Reciprocal Rank Fusion for hybrid retrieval (plan §18.3, §18.4; session 24).

Dense (vector) and lexical (full-text) retrieval each return candidates ranked *within their own
branch*. Their raw scores are not comparable (cosine similarity vs ``ts_rank_cd``), so we fuse by
rank, not by score: a candidate's fused score is the weighted sum of ``weight / (k0 + rank)`` over
the branches that returned it (plan §18.3). A candidate returned by *both* branches therefore
outranks one returned by a single branch at a comparable rank.

Candidate diversity (plan §18.4) is applied after scoring, always keeping the highest-ranked
survivors:

- **dedupe by chunk id** — the same chunk returned by both branches is merged into one hit;
- **near-duplicate cap by content hash** — at most ``max_per_content_hash`` chunks sharing a
  ``content_hash`` survive, so duplicated passages cannot flood the reranker input;
- **per-document cap** — at most ``max_per_document`` chunks from a single document survive, so one
  long document cannot monopolise results. The cap is intentionally greater than one so that
  ordinally contiguous chunks from a promising document can all survive, preserving the
  same-document continuity needed for answers that span paragraphs.

This module is pure: no I/O, no database, fully deterministic given its inputs.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.rag.types import RankedHit


class FusionConfig(BaseModel):
    """Baseline RRF parameters (plan §18.3). These are experiment starting points, tuned by
    evaluation rather than treated as production truth."""

    model_config = ConfigDict(frozen=True)

    k0: float = Field(default=60.0, gt=0, description="RRF damping constant")
    dense_weight: float = Field(default=0.55, ge=0, description="Weight of the dense branch")
    lexical_weight: float = Field(default=0.45, ge=0, description="Weight of the lexical branch")
    max_per_document: int = Field(
        default=3,
        ge=1,
        description="Max chunks kept from one document (>1 preserves same-document continuity)",
    )
    max_per_content_hash: int = Field(
        default=1, ge=1, description="Max chunks kept with an identical content_hash"
    )


def reciprocal_rank_fusion(
    dense_hits: Sequence[RankedHit],
    lexical_hits: Sequence[RankedHit],
    config: FusionConfig | None = None,
) -> list[RankedHit]:
    """Fuse two ranked branches into one list ordered by weighted RRF score.

    Preconditions: within each branch, chunk ids are unique and ranks are 1-based and ascending;
    the same chunk id may appear in both branches (it is merged). Inputs are assumed to be already
    authorized — this function performs no access checks.

    Returns the fused ``RankedHit``s with ``fused_score`` populated, ordered by descending fused
    score (ties broken by chunk id for a deterministic total order), after applying the diversity
    caps from ``config``.
    """
    cfg = config if config is not None else FusionConfig()

    # 1. Merge by chunk id, keeping each branch's native rank/score and clearing the other branch's
    #    fields so the merged hit carries exactly one contribution per branch.
    merged: dict[uuid.UUID, RankedHit] = {}
    for hit in dense_hits:
        merged[hit.chunk_id] = hit.model_copy(update={"lexical_rank": None, "lexical_score": None})
    for hit in lexical_hits:
        base = merged.get(hit.chunk_id)
        if base is None:
            merged[hit.chunk_id] = hit.model_copy(update={"dense_rank": None, "dense_score": None})
        else:
            merged[hit.chunk_id] = base.model_copy(
                update={"lexical_rank": hit.lexical_rank, "lexical_score": hit.lexical_score}
            )

    # 2. Weighted RRF score per candidate; a branch that did not return the candidate adds nothing.
    scored: list[tuple[float, RankedHit]] = []
    for hit in merged.values():
        score = 0.0
        if hit.dense_rank is not None:
            score += cfg.dense_weight / (cfg.k0 + hit.dense_rank)
        if hit.lexical_rank is not None:
            score += cfg.lexical_weight / (cfg.k0 + hit.lexical_rank)
        scored.append((score, hit))

    # 3. Order by fused score (descending); chunk id gives a deterministic total order on ties.
    scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))

    # 4. Diversity caps, keeping the highest-ranked survivors (iteration is in score order).
    content_hash_counts: defaultdict[str, int] = defaultdict(int)
    document_counts: defaultdict[uuid.UUID, int] = defaultdict(int)
    result: list[RankedHit] = []
    for score, hit in scored:
        content_hash = hit.candidate.content_hash
        document_id = hit.candidate.document_id
        if content_hash_counts[content_hash] >= cfg.max_per_content_hash:
            continue
        if document_counts[document_id] >= cfg.max_per_document:
            continue
        content_hash_counts[content_hash] += 1
        document_counts[document_id] += 1
        result.append(hit.model_copy(update={"fused_score": score}))
    return result
