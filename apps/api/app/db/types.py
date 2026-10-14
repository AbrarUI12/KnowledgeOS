"""Column types the stock SQLAlchemy PostgreSQL dialect lacks."""

import math
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.types import UserDefinedType


def vector_literal(values: Sequence[float]) -> str:
    """pgvector's text form, `[0.1,0.2,…]`. Non-finite values are refused (pgvector would too)."""
    if not all(math.isfinite(v) for v in values):
        raise ValueError("vector contains NaN or infinity")
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def parse_vector(text: str) -> list[float]:
    return [float(part) for part in text.strip("[]").split(",")] if text != "[]" else []


class Vector(UserDefinedType[list[float]]):
    """pgvector `vector(n)`. asyncpg has no codec for it and uses its text form, so values travel
    as `[…]` strings; this keeps the pgvector package out of the dependency list."""

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect: Any) -> Callable[[Sequence[float] | None], str | None]:
        def process(value: Sequence[float] | None) -> str | None:
            return None if value is None else vector_literal(value)

        return process

    def result_processor(
        self, dialect: Any, coltype: Any
    ) -> Callable[[str | None], list[float] | None]:
        def process(value: str | None) -> list[float] | None:
            return None if value is None else parse_vector(value)

        return process
