"""Recursive paragraph/line/sentence/token splitting experiment, without parent expansion."""

from pathlib import Path

from app.ingestion.canonical import CanonicalDocument
from app.ingestion.chunking.core import TextTokenizer
from app.ingestion.chunking.structure_aware import StructureAwareChunker
from app.ingestion.chunking.types import ChunkDraft, ChunkerConfig


class RecursiveFixedChunker(StructureAwareChunker):
    name = "recursive_fixed"

    def __init__(
        self,
        config: ChunkerConfig | None = None,
        *,
        tokenizer: TextTokenizer | None = None,
        tokenizer_file: Path | None = None,
    ) -> None:
        super().__init__(
            config or ChunkerConfig(name="recursive_fixed"),
            tokenizer=tokenizer,
            tokenizer_file=tokenizer_file,
        )

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]:
        return self._chunk(document, parents=False, recursive=True)
