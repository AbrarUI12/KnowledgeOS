"""Pure, conservative content heuristics. Findings contain IDs, never source text."""

import ipaddress
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ingestion.canonical import CanonicalDocument
from app.security.content_types import ContentFinding, ContentScanOutcome, ContentScanResult

RULE_IDS = frozenset(
    {
        "injection.phrase",
        "injection.role_marker",
        "unicode.invisible_density",
        "encoded.long_blob",
        "link.suspicious",
        "repetition.dominance",
        "content.type_mismatch",
    }
)
_ROLE = re.compile(
    r"(?:^|\n)\s*(?:system|developer|assistant|user)\s*:|"
    r"\[/?(?:system|inst)\]|<\|(?:im_start|im_end|system|assistant|user|start_header_id)\|>|"
    r"(?:^|\n)\s*#{1,6}\s*(?:instruction|system|developer)\b",
    re.IGNORECASE,
)
_URL = re.compile(r"(?:https?://|javascript\s*:|data\s*:)[^\s<>\"']*", re.IGNORECASE)
_WORDS = re.compile(r"\w+", re.UNICODE)


class RulePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    weight: float = Field(gt=0, allow_inf_nan=False)
    severity: int = Field(ge=1, le=5)


class ScanPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    flagged_score: float = Field(gt=0, allow_inf_nan=False)
    quarantined_score: float = Field(gt=0, allow_inf_nan=False)
    rejected_score: float = Field(gt=0, allow_inf_nan=False)
    invisible_min_count: int = Field(ge=1)
    invisible_density: float = Field(gt=0, le=1)
    encoded_min_length: int = Field(ge=64, le=4096)
    repetition_min_words: int = Field(ge=10)
    repetition_ngram_share: float = Field(gt=0, le=1)
    injection_phrases: tuple[str, ...] = Field(min_length=1)
    rules: dict[str, RulePolicy]

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if not self.flagged_score < self.quarantined_score < self.rejected_score:
            raise ValueError("scan thresholds must be strictly increasing")
        if self.rules.keys() != RULE_IDS:
            raise ValueError("all supported rules must be configured exactly once")
        if any(not phrase.strip() for phrase in self.injection_phrases):
            raise ValueError("empty injection phrases are not allowed")
        return self


def default_policy_path() -> Path:
    # Both repository checkouts and the worker's /app/configs layout; never fall back to CLEAN
    # or a different policy when a deployment forgot its policy files.
    for root in (Path.cwd(), *Path(__file__).resolve().parents):
        candidate = root / "configs" / "policies" / "content_scan.yaml"
        if candidate.is_file():
            return candidate
    raise ValueError("content_scan_policy_missing")


def detection_view(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFC", text).casefold()
        if unicodedata.category(char) != "Cf"
    )


def suspicious_link(url: str) -> bool:
    url = detection_view(url).strip()
    if re.match(r"(?:javascript|data)\s*:", url):
        return True
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return True
    if not host:
        return False
    if any(label.startswith("xn--") for label in host.split(".")):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


class RuleContentScanner:
    def __init__(
        self, *, policy_path: Path | None = None, policy: ScanPolicy | None = None
    ) -> None:
        if policy is not None and policy_path is not None:
            raise ValueError("supply a policy or path, not both")
        self.policy = policy or ScanPolicy.model_validate(
            yaml.safe_load((policy_path or default_policy_path()).read_text(encoding="utf-8"))
        )
        self._phrases = tuple(detection_view(phrase) for phrase in self.policy.injection_phrases)
        length = self.policy.encoded_min_length
        self._blob = re.compile(
            rf"(?<![\w+/])[A-Za-z0-9+/]{{{length},}}={{0,2}}(?![\w+/])|"
            rf"(?<!\w)[0-9a-fA-F]{{{length},}}(?!\w)"
        )

    def scan(self, document: CanonicalDocument) -> ContentScanResult:
        matches: dict[str, list[str]] = {}

        def record(rule: str, block_id: str | None = None) -> None:
            ids = matches.setdefault(rule, [])
            if block_id is not None and block_id not in ids:
                ids.append(block_id)

        def scan_text(raw: str, block_id: str | None, removed: int = 0) -> str:
            view = detection_view(raw)
            collapsed = " ".join(view.split())
            if any(phrase in collapsed for phrase in self._phrases):
                record("injection.phrase", block_id)
            if _ROLE.search(view):
                record("injection.role_marker", block_id)
            present = sum(unicodedata.category(char) == "Cf" for char in raw)
            invisible = max(removed, present)
            if (
                invisible >= self.policy.invisible_min_count
                and invisible / max(1, len(raw) + max(0, removed - present))
                >= self.policy.invisible_density
            ):
                record("unicode.invisible_density", block_id)
            if self._blob.search(view):
                record("encoded.long_blob", block_id)
            if any(suspicious_link(match.group()) for match in _URL.finditer(view)):
                record("link.suspicious", block_id)
            if self._repetition(view):
                record("repetition.dominance", block_id)
            return view

        scan_text(document.title, None)
        bodies = []
        total_removed = 0
        for block in document.blocks:
            removed = block.extra.get("removed_invisible_controls", 0)
            removed = removed if isinstance(removed, int) and removed > 0 else 0
            # The forensic copy survives normalization; do not double-count invisible controls.
            raw = block.raw_text if block.raw_text is not None else block.text
            bodies.append(raw)
            total_removed += removed
            scan_text(raw, block.block_id, removed)
            scan_text("\n".join(block.heading_path), block.block_id)
            if block.table is not None:
                scan_text(
                    "\n".join(" | ".join(row) for row in [block.table.header, *block.table.rows]),
                    block.block_id,
                )
        previous_rules = set(matches)
        scan_text("\n".join(bodies), None, total_removed)
        # Also catch phrases/density/floods fragmented into small canonical blocks. These
        # aggregate findings conservatively reference all contributing nonempty blocks.
        for rule in matches.keys() - previous_rules:
            for block in document.blocks:
                if block.text or block.raw_text:
                    record(rule, block.block_id)
        # HTML adapters retain hrefs as untrusted metadata; never fetch or resolve them.
        links = document.metadata.get("links", [])
        if isinstance(links, list) and any(
            isinstance(link, str) and suspicious_link(link) for link in links
        ):
            record("link.suspicious")
        flags = document.metadata.get("validation_flags", [])
        if isinstance(flags, (list, tuple)) and any(
            flag in {"mime_mismatch", "polyglot_content"} for flag in flags if isinstance(flag, str)
        ):
            record("content.type_mismatch")
        score = sum(self.policy.rules[rule].weight for rule in matches)
        outcome = ContentScanOutcome.CLEAN
        for threshold, candidate in (
            (self.policy.flagged_score, ContentScanOutcome.FLAGGED),
            (self.policy.quarantined_score, ContentScanOutcome.QUARANTINED),
            (self.policy.rejected_score, ContentScanOutcome.REJECTED),
        ):
            if score >= threshold:
                outcome = candidate
        return ContentScanResult(
            outcome=outcome,
            score=score,
            rules_version=self.policy.version,
            findings=tuple(
                ContentFinding(
                    rule_id=rule, severity=self.policy.rules[rule].severity, block_ids=tuple(ids)
                )
                for rule, ids in sorted(matches.items())
            ),
        )

    def _repetition(self, text: str) -> bool:
        words = _WORDS.findall(text)
        if len(words) < self.policy.repetition_min_words:
            return False
        grams = Counter(zip(words, words[1:], words[2:], strict=False))
        return (
            bool(grams)
            and max(grams.values()) / (len(words) - 2) >= self.policy.repetition_ngram_share
        )
