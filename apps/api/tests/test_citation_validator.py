import hashlib
import uuid

import pytest

from app.ingestion.canonical import SourceLocation
from app.rag.citations.validator import validate_citations
from app.rag.types import EvidenceItem, SourceAlias

pytestmark = [pytest.mark.unit, pytest.mark.security]


def item(alias: str = "S1") -> EvidenceItem:
    content = "Eligible employees receive sixteen weeks of leave."
    return EvidenceItem(
        source=SourceAlias(
            alias=alias,
            chunk_id=uuid.UUID(int=1),
            document_id=uuid.UUID(int=2),
            document_version_id=uuid.UUID(int=3),
            title="Policy",
            version_number=2,
            location=SourceLocation(page_start=4, page_end=4),
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
        ),
        content=content,
        token_count=10,
    )


def test_single_and_grouped_aliases_use_only_stored_metadata() -> None:
    evidence = [item(), item("S3")]
    result = validate_citations("Sixteen weeks [S1, S3]. Apply early [S1].", evidence)
    assert result.valid
    assert [citation.alias for citation in result.citations] == ["S1", "S3"]
    assert result.citations[0].location.page_start == 4
    assert result.citations[0].document_version_id == uuid.UUID(int=3)
    assert result.citations[0] == evidence[0].source


@pytest.mark.parametrize(
    "answer",
    [
        "Claim [S999].",
        "Claim [S1, S999].",
        "Claim [S0].",
        "Claim [S01].",
        "Claim [s1].",
        "Claim [S1 page=99].",
        "Claim \uff3bS1\uff3d.",
        "Claim [S\u200b1].",
        "Claim [S1](https://evil.example/page99).",
        "Claim ![S1](image).",
        "Claim [[S1]].",
        "Claim [S1",
        "Claim [S1]. Fake [S999" + "x" * 300 + "].",
        "Claim [S1]. Fake [\u200bS999",
    ],
)
def test_unknown_and_tampered_aliases_never_return_partial_citations(answer: str) -> None:
    result = validate_citations(answer, [item()])
    assert not result.valid
    assert result.errors
    assert result.citations == ()


def test_missing_citation_fails_except_for_caller_declared_abstention() -> None:
    assert "missing_citation" in validate_citations("Sixteen weeks.", [item()]).errors
    assert validate_citations("Insufficient evidence.", [], abstained=True).valid
    assert not validate_citations("Insufficient evidence [S999].", [], abstained=True).valid


def test_modified_content_and_duplicate_source_registry_fail_closed() -> None:
    original = item()
    tampered = original.model_copy(update={"content": "Compensation is public."})
    assert validate_citations("Claim [S1].", [tampered]).errors == ("tampered_evidence",)
    assert validate_citations("Claim [S1].", [original, original]).errors == ("invalid_source_map",)
    assert original.content.startswith("Eligible")


def test_limits_fail_closed() -> None:
    assert validate_citations("a" * 100_001, [item()]).errors == ("validation_limit",)
