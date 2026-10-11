"""Shared API schema building blocks (T1.0)."""

from typing import Any

from pydantic import BaseModel, Field


class Page[T](BaseModel):
    """Cursor-paginated list (plan §26.1). Pass `next_cursor` back as `?cursor=` to continue."""

    items: list[T]
    next_cursor: str | None = Field(default=None, description="Opaque; None when there are no more")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code, see docs/api/errors.md")
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody


ORG_HEADER = "X-Organization-Id"
ORG_HEADER_DESCRIPTION = (
    "Organization the request acts in. Required for org-scoped resources that aren't under "
    "/v1/organizations/{org_id}. The caller must be an active member (otherwise 404)."
)
