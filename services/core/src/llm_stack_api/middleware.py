"""Per-request context: a correlation id, one access line, and the HTTP metrics."""

import logging
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from llm_stack_core.observability import (
    http_request_duration,
    http_requests,
    request_id,
)

REQUEST_ID_HEADER = b"x-request-id"
UNMATCHED_ROUTE = "unmatched"
UNREPORTED_STATUS = 500

logger = logging.getLogger(__name__)


class RequestContext:
    """Binds a request id for the life of the request and records the outcome."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        identifier = _incoming_request_id(scope) or str(uuid4())
        token = request_id.set(identifier)
        status = UNREPORTED_STATUS
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (REQUEST_ID_HEADER, identifier.encode()),
                ]
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            duration = time.perf_counter() - started
            route = _route(scope)
            method = scope["method"]

            http_requests.labels(method, route, str(status)).inc()
            http_request_duration.labels(method, route).observe(duration)
            logger.info(
                "request",
                extra={
                    "method": method,
                    "route": route,
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            request_id.reset(token)


def _incoming_request_id(scope: Scope) -> str | None:
    for key, value in scope["headers"]:
        if key == REQUEST_ID_HEADER:
            return value.decode()
    return None


def _route(scope: Scope) -> str:
    """The matched route template. A raw path is unbounded label cardinality."""
    return getattr(scope.get("route"), "path", UNMATCHED_ROUTE)
