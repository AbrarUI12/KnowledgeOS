"""Stable JSON error envelope and exception handlers.

Every error response has the shape:

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": {...}}}

`code` values are stable, machine-readable and documented in docs/api/errors.md.
"""

from collections.abc import Mapping
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import REQUEST_ID_HEADER, current_request_id

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for errors that map to a safe, documented API response."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."
    headers: Mapping[str, str] = {}

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}


class ValidationFailed(AppError):
    status_code, code, message = 422, "validation_failed", "The request is invalid."


class Unauthorized(AppError):
    status_code, code, message = 401, "unauthorized", "Authentication is required."


class Forbidden(AppError):
    status_code, code, message = 403, "forbidden", "You do not have permission to do this."


class NotFound(AppError):
    status_code, code, message = 404, "not_found", "The resource was not found."


class Conflict(AppError):
    status_code, code, message = 409, "conflict", "The request conflicts with the current state."


class Gone(AppError):
    status_code, code, message = 410, "gone", "The resource is no longer available."


# Domain-specific codes (docs/api/errors.md). Subclasses keep the HTTP status of their parent.
class SlugTaken(Conflict):
    code, message = "slug_taken", "That organization slug is already in use."


class LastOwner(Conflict):
    code, message = "last_owner", "An organization must keep at least one owner."


class AlreadyMember(Conflict):
    code, message = "already_member", "That person is already a member of this organization."


class GroupNameTaken(Conflict):
    code, message = "group_name_taken", "A group with that name already exists."


class IdempotencyKeyReused(Conflict):
    code, message = (
        "idempotency_key_reused",
        "This Idempotency-Key was already used for a different request.",
    )


class InvitationExpired(Gone):
    code, message = "invitation_expired", "This invitation has expired."


class InvitationEmailMismatch(Forbidden):
    code, message = (
        "invitation_email_mismatch",
        "This invitation was sent to a different email address.",
    )


class RateLimited(AppError):
    status_code, code, message = 429, "rate_limited", "Too many requests."


class NotImplementedYet(AppError):
    """Contract stub (T1.0): the endpoint exists with its final schema but isn't implemented yet."""

    status_code, code, message = 501, "not_implemented", "This endpoint is not implemented yet."

    def __init__(self, task: str) -> None:
        super().__init__(f"Not implemented yet (task {task}).", details={"task": task})


class ServiceUnavailable(AppError):
    status_code, code, message = 503, "service_unavailable", "A dependency is unavailable."


_HTTP_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
    501: "not_implemented",
}


def error_response(
    request: Request | None,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = current_request_id(request.scope if request is not None else None)
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details or {},
        }
    }
    all_headers = dict(headers or {})
    if request_id:
        all_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(status_code=status_code, content=body, headers=all_headers)


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppError, exc)
    return error_response(
        request, exc.status_code, exc.code, exc.message, exc.details, headers=exc.headers
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    return error_response(request, exc.status_code, code, message, headers=exc.headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    # Never echo the submitted input back: it may contain secrets.
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(
        request, 422, "validation_failed", "The request is invalid.", {"errors": errors}
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error", error_type=type(exc).__name__)
    return error_response(request, 500, "internal_error", "An unexpected error occurred.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
