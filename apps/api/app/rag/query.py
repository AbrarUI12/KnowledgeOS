"""Query normalization (plan §16.2): what search and question answering see and record.

Trim, Unicode NFC, invisible controls removed (a query can't smuggle zero-width or bidi tricks
into lexical matching), whitespace collapsed, length capped; plus a stable hash for query runs
and a best-effort language for the record. Language detection abstains on short queries.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from lingua import LanguageDetector, LanguageDetectorBuilder

MAX_QUERY_CHARACTERS = 2000
_INVISIBLE = re.compile(r"[؜​-‏‪-‮⁠-⁩﻿]")


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    text: str
    hash: str
    language: str | None


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    return (
        LanguageDetectorBuilder.from_all_languages()
        .with_low_accuracy_mode()
        .with_minimum_relative_distance(0.25)
        .build()
    )


def detect_language(text: str) -> str | None:
    """ISO 639-1 code, or None when the text is too short or ambiguous to tell."""
    if sum(character.isalpha() for character in text) < 12:
        return None
    detected = _detector().detect_language_of(text)
    return detected.iso_code_639_1.name.lower() if detected is not None else None


def normalize_query(raw: str, *, max_characters: int = MAX_QUERY_CHARACTERS) -> NormalizedQuery:
    text = _INVISIBLE.sub("", unicodedata.normalize("NFC", raw))
    text = " ".join(text.split())[:max_characters].strip()
    if not text:
        raise ValueError("the query is empty after normalization")
    return NormalizedQuery(
        text=text,
        hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        language=detect_language(text),
    )
