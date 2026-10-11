"""Helpers for T1.0 contract stubs. Implementing tasks replace each stub body with the real
logic."""

import uuid
from typing import Annotated, Any, NoReturn

from fastapi import Header

from app.api.errors import NotImplementedYet
from app.domain.schemas.common import ORG_HEADER, ORG_HEADER_DESCRIPTION, ErrorEnvelope

OrgIdHeader = Annotated[uuid.UUID, Header(alias=ORG_HEADER, description=ORG_HEADER_DESCRIPTION)]

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorEnvelope, "description": "Missing or invalid token"},
    403: {"model": ErrorEnvelope, "description": "Missing permission"},
    404: {"model": ErrorEnvelope, "description": "Not found or not visible to the caller"},
    422: {"model": ErrorEnvelope, "description": "Validation failed"},
    501: {"model": ErrorEnvelope, "description": "Contract stub, not implemented yet"},
}


def stub(task: str) -> NoReturn:
    raise NotImplementedYet(task)
