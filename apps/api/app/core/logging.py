"""Structured logging (structlog) with secret redaction and request-scoped context."""

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"(authorization|password|passwd|secret|token|api[_-]?key|cookie|credential|dsn)", re.I
)
REDACTED = "[REDACTED]"


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace values of sensitive-looking keys (recursively) so secrets never reach logs."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: REDACTED if _SENSITIVE_KEY.search(str(k)) else scrub(v) for k, v in value.items()
            }
        if isinstance(value, list | tuple):
            return [scrub(v) for v in value]
        return value

    for key in list(event_dict.keys()):
        if key != "event" and _SENSITIVE_KEY.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = scrub(event_dict[key])
    return event_dict


def configure_logging(*, level: str = "INFO", json_logs: bool = True) -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    # Route stdlib logging (uvicorn, sqlalchemy) through the same level.
    logging.basicConfig(level=level.upper(), stream=sys.stderr, format="%(message)s")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
