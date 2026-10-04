"""Structured logging and metrics. Knows nothing about HTTP, by ADR 0001."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from prometheus_client import Counter, Histogram

LATENCY_BUCKETS = (0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
ACCESS_LOGGER = "uvicorn.access"

RECORD_ATTRIBUTES = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so a log stream can be queried rather than read."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        bound = request_id.get()
        if bound is not None:
            payload["request_id"] = bound

        payload.update(
            {
                key: value
                for key, value in vars(record).items()
                if key not in RECORD_ATTRIBUTES
            }
        )

        if record.exc_info:
            payload["stack"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


_installed: logging.Handler | None = None


def configure_logging(level: str) -> None:
    """Send the root logger to stdout as JSON. Safe to call more than once."""
    global _installed

    root = logging.getLogger()
    if _installed is not None:
        root.removeHandler(_installed)

    _installed = logging.StreamHandler()
    _installed.setFormatter(JsonFormatter())
    root.addHandler(_installed)
    root.setLevel(level)

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # RequestContext writes the access line. uvicorn decides whether to write its
    # own by asking hasHandlers(), so leaving this one unreachable is the off switch.
    access = logging.getLogger(ACCESS_LOGGER)
    access.handlers = []
    access.propagate = False


http_requests = Counter(
    "http_requests_total",
    "HTTP requests completed.",
    ("method", "route", "status"),
)
http_request_duration = Histogram(
    "http_request_duration_seconds",
    "Wall time from request received to response finished.",
    ("method", "route"),
    buckets=LATENCY_BUCKETS,
)
inference_requests = Counter(
    "inference_requests_total",
    "Chat streams finished, by outcome.",
    ("backend", "model", "outcome"),
)
inference_time_to_first_fragment = Histogram(
    "inference_time_to_first_fragment_seconds",
    "Wall time from prompt sent to first fragment received.",
    ("backend", "model"),
    buckets=LATENCY_BUCKETS,
)
inference_stream_duration = Histogram(
    "inference_stream_duration_seconds",
    "Wall time of a whole chat stream.",
    ("backend", "model"),
    buckets=LATENCY_BUCKETS,
)
