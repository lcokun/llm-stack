"""Structured logging: one queryable object per event, and who can reach a handler."""

import json
import logging
from collections.abc import Callable, Iterator
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest

from llm_stack_core.observability import (
    ACCESS_LOGGER,
    JsonFormatter,
    configure_logging,
    request_id,
)

LOGGER_NAME = "test.observability"

LogLine = Callable[..., dict[str, Any]]


@pytest.fixture
def log_line() -> Iterator[LogLine]:
    """Emit one record through JsonFormatter and hand back the parsed object."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    def emit(message: str, **kwargs: Any) -> dict[str, Any]:
        stream.seek(0)
        stream.truncate()
        logger.info(message, **kwargs)
        return json.loads(stream.getvalue())

    yield emit

    logger.handlers = []


def test_every_line_carries_the_standard_fields(log_line: LogLine) -> None:
    line = log_line("hello")

    assert line["level"] == "INFO"
    assert line["logger"] == LOGGER_NAME
    assert line["msg"] == "hello"
    assert line["ts"].endswith("+00:00")


def test_request_id_is_absent_until_bound(log_line: LogLine) -> None:
    assert "request_id" not in log_line("hello")


def test_request_id_is_attached_once_bound(log_line: LogLine) -> None:
    token = request_id.set("abc-123")
    try:
        assert log_line("hello")["request_id"] == "abc-123"
    finally:
        request_id.reset(token)


def test_extra_fields_become_top_level_keys(log_line: LogLine) -> None:
    line = log_line("request", extra={"route": "/healthz", "status": 200})

    assert line["route"] == "/healthz"
    assert line["status"] == 200


def test_unserialisable_values_do_not_break_logging(log_line: LogLine) -> None:
    identifier = uuid4()

    line = log_line("created", extra={"conversation_id": identifier})

    assert line["conversation_id"] == str(identifier)


def test_a_traceback_is_captured_as_a_string_field(log_line: LogLine) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        line = log_line("failed", exc_info=True)

    assert "Traceback" in line["stack"]
    assert "ValueError: boom" in line["stack"]


def test_uvicorn_access_logging_is_left_unreachable() -> None:
    """RequestContext is the access log, so uvicorn's must stay switched off."""
    configure_logging("INFO")

    assert logging.getLogger(ACCESS_LOGGER).hasHandlers() is False
