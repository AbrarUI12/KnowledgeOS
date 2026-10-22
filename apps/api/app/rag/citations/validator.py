"""Mechanical citation integrity, not a semantic claim-support verifier.

Only the caller's selected, authorized EvidenceItems supply source metadata. An invalid answer
returns NO citation objects: callers must discard it or use the single bounded correction path.
Never extract page/version/URL metadata from model text.
"""

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from app.rag.types import EvidenceItem, SourceAlias

_GROUP = re.compile(r"[\[\uff3b]([^\]\n\uff3d]{0,200})[\]\uff3d]")
_OPEN = re.compile(r"[\[\uff3b]")
_VALID = re.compile(r"S[1-9][0-9]*(?:\s*,\s*S[1-9][0-9]*)*")
_ALIAS = re.compile(r"S[1-9][0-9]*")


@dataclass(frozen=True)
class CitationValidation:
    errors: tuple[str, ...]
    citations: tuple[SourceAlias, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_citations(
    text: str,
    evidence: Sequence[EvidenceItem],
    *,
    abstained: bool = False,
) -> CitationValidation:
    """Validate `[S1]` and `[S1, S3]`. Bounds keep malformed nested brackets cheap to inspect.
    `abstained` is a caller decision, never inferred here from untrusted model metadata.
    """
    if len(text) > 100_000 or len(evidence) > 32:
        return CitationValidation(("validation_limit",))
    registry: dict[str, SourceAlias] = {}
    for item in evidence:
        if not _ALIAS.fullmatch(item.source.alias) or item.source.alias in registry:
            return CitationValidation(("invalid_source_map",))
        if hashlib.sha256(item.content.encode()).hexdigest() != item.source.content_hash:
            return CitationValidation(("tampered_evidence",))
        registry[item.source.alias] = item.source
    errors: set[str] = set()
    names: dict[str, None] = {}
    covered: set[int] = set()
    for match in _GROUP.finditer(text):
        raw = match.group(1)
        view = "".join(
            char
            for char in unicodedata.normalize("NFKC", raw)
            if unicodedata.category(char) != "Cf"
        ).strip()
        if not view.casefold().startswith("s"):
            continue
        covered.add(match.start())
        # Detect confusable/hidden aliases, but never normalize them into accepted citations.
        if (
            match.group(0)[0] != "["
            or match.group(0)[-1] != "]"
            or view != raw.strip()
            or not _VALID.fullmatch(raw.strip())
            or text[match.end() :].lstrip().startswith("(")
            or (match.start() > 0 and text[match.start() - 1] == "!")
        ):
            errors.add("malformed_citation")
            continue
        for name in re.findall(r"S[1-9][0-9]*", raw):
            if name not in registry:
                errors.add("unknown_alias")
            else:
                names[name] = None
    for opening in _OPEN.finditer(text):
        tail = text[opening.end() : opening.end() + 200]
        view = "".join(
            char
            for char in unicodedata.normalize("NFKC", tail)
            if unicodedata.category(char) != "Cf"
        ).lstrip()
        if (not view or view.casefold().startswith("s")) and opening.start() not in covered:
            errors.add("malformed_citation")
    if not abstained and not names:
        errors.add("missing_citation")
    if errors:
        return CitationValidation(tuple(sorted(errors)))
    return CitationValidation((), tuple(registry[name].model_copy(deep=True) for name in names))
