"""Embedding-model tokenization, without decoding/replacing source Unicode."""

import hashlib
import json
from pathlib import Path

from tokenizers import Tokenizer


class ModelTokenizer:
    def __init__(self, model: str, *, tokenizer_file: Path | None = None) -> None:
        self.model = model
        self.tokenizer_file = tokenizer_file
        self._backend: Tokenizer | None = None
        self._fingerprint: str | None = None

    @property
    def backend(self) -> Tokenizer:
        if self._backend is None:
            # Failure is explicit: never substitute another model or a word-count heuristic.
            self._backend = (
                Tokenizer.from_file(str(self.tokenizer_file))
                if self.tokenizer_file is not None
                else Tokenizer.from_pretrained(self.model)
            )
            self._backend.no_truncation()
            self._backend.no_padding()
        return self._backend

    def count(self, text: str) -> int:
        return len(self.backend.encode(text, add_special_tokens=False).ids)

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return self.backend.encode(text, add_special_tokens=False).offsets

    @property
    def fingerprint(self) -> str:
        if self._fingerprint is None:
            canonical = json.dumps(
                json.loads(self.backend.to_str()), sort_keys=True, separators=(",", ":")
            )
            self._fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        return self._fingerprint
