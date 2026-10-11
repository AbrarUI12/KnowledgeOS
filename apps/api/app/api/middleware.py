"""Pure-ASGI middleware: request IDs, timing and access logging.

Implemented as raw ASGI (not BaseHTTPMiddleware) so it never buffers streaming responses (SSE).
"""

import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
access_logger = structlog.get_logger("app.access")


def current_request_id(scope: Scope | None = None) -> str | None:
    """Request ID for the current request (context var, or the ASGI scope when given)."""
    if scope is not None:
        state = scope.get("state") or {}
        if state.get("request_id"):
            return str(state["request_id"])
    return _request_id.get()


def _incoming_request_id(scope: Scope) -> str:
    """Accept a client-supplied request ID only if it is a valid UUID; otherwise generate one."""
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            try:
                return str(uuid.UUID(value.decode("latin-1")))
            except ValueError:
                break
    return str(uuid.uuid4())


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        # Also kept in the scope: the outermost error handler runs after the context var resets.
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            access_logger.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id.reset(token)
