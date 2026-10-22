"""PostgreSQL full-text configurations for detected languages (indexing and search agree)."""

# Detected language (ISO 639-1) → PostgreSQL text search configuration; anything else → simple.
FTS_CONFIGS: dict[str, str] = {
    "ar": "arabic", "ca": "catalan", "da": "danish", "de": "german", "el": "greek",
    "en": "english", "es": "spanish", "eu": "basque", "fi": "finnish", "fr": "french",
    "ga": "irish", "hi": "hindi", "hu": "hungarian", "hy": "armenian", "id": "indonesian",
    "it": "italian", "lt": "lithuanian", "nb": "norwegian", "ne": "nepali", "nl": "dutch",
    "no": "norwegian", "pt": "portuguese", "ro": "romanian", "ru": "russian", "sr": "serbian",
    "sv": "swedish", "ta": "tamil", "tr": "turkish", "yi": "yiddish",
}  # fmt: skip

SEARCH_CONFIGS: tuple[str, ...] = tuple(sorted({*FTS_CONFIGS.values(), "simple"}))


def fts_config(language: str | None) -> str:
    """The configuration for an ISO 639-1 code; `simple` (no stemming) for anything else."""
    return FTS_CONFIGS.get(language or "", "simple")
