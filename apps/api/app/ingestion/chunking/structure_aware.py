"""Deterministic structure-aware parent/child chunking of canonical artifacts."""

from pathlib import Path

from app.ingestion.canonical import CanonicalDocument
from app.ingestion.chunking.core import (
    TextTokenizer,
    child_units,
    draft,
    join_units,
    parent_groups,
    sections,
    validate_config,
)
from app.ingestion.chunking.tokenizer import ModelTokenizer
from app.ingestion.chunking.types import ChunkDraft, ChunkerConfig


class StructureAwareChunker:
    name = "structure_aware"
    version = "1"

    def __init__(
        self,
        config: ChunkerConfig | None = None,
        *,
        tokenizer: TextTokenizer | None = None,
        tokenizer_file: Path | None = None,
    ) -> None:
        self._config = config or ChunkerConfig(name=self.name, version=self.version)
        if self._config.name != self.name or self._config.version != self.version:
            raise ValueError("chunker name/version does not match implementation")
        validate_config(self._config)
        if isinstance(tokenizer, ModelTokenizer) and tokenizer.model != self._config.tokenizer:
            raise ValueError("tokenizer model does not match chunker configuration")
        self.tokenizer = tokenizer or ModelTokenizer(
            self._config.tokenizer, tokenizer_file=tokenizer_file
        )

    @property
    def config(self) -> ChunkerConfig:
        return self._config

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]:
        return self._chunk(document, parents=True, recursive=False)

    def _chunk(
        self, document: CanonicalDocument, *, parents: bool, recursive: bool
    ) -> list[ChunkDraft]:
        result: list[ChunkDraft] = []
        for path, blocks in sections(document):
            units = child_units(blocks, self.tokenizer, self.config, recursive)
            groups = parent_groups(units, self.tokenizer, self.config) if parents else [units]
            for group in groups:
                parent = None
                if parents:
                    parent = len(result)
                    result.append(
                        draft(
                            join_units(group),
                            document,
                            path,
                            self.tokenizer,
                            self.config,
                            parent,
                            is_parent=True,
                        )
                    )
                for unit in group:
                    result.append(
                        draft(
                            unit,
                            document,
                            path,
                            self.tokenizer,
                            self.config,
                            len(result),
                            parent=parent,
                        )
                    )
        return result
