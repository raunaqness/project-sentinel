"""JSON logs on stdout, one object per line, with correlation ids from context.

Use `log_context(tenant_id=..., transaction_id=...)` around a unit of work and every
log line inside it carries those fields. Extra per-line fields go in `extra={...}`.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from sentinel.config import get_settings

_context: ContextVar[dict[str, str]] = ContextVar("log_context", default={})  # noqa: B039

# Attributes every LogRecord has; anything else was passed via `extra=`.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "color_message",
    "taskName",
}


def context_value(key: str) -> str | None:
    return _context.get().get(key)


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    merged = _context.get() | {k: v for k, v in fields.items() if v is not None}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
            **_context.get(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(get_settings().log_level)
    # The OpenAI SDK's HTTP client logs every request at INFO; keep only problems.
    for name in ("httpx", "httpx2", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # Route uvicorn's own loggers through the JSON handler too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
