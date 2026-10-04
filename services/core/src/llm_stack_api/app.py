"""The HTTP layer. Owns the pool, the inference client and the wire format."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from psycopg import AsyncConnection
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from llm_stack_api import problems, routes
from llm_stack_api.middleware import RequestContext
from llm_stack_core.chat import ChatService
from llm_stack_core.config import Settings, get_settings
from llm_stack_core.conversations.store import ConversationNotFoundError
from llm_stack_core.inference.base import InferenceClient
from llm_stack_core.inference.fake import FakeClient
from llm_stack_core.observability import configure_logging

Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]

logger = logging.getLogger(__name__)


def build_client(settings: Settings) -> InferenceClient:
    """Choose a backend from the configuration."""
    if settings.inference_backend == "fake":
        return FakeClient()
    raise NotImplementedError(
        f"inference backend {settings.inference_backend!r} is not implemented yet"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    client = build_client(settings)
    logger.info(
        "starting",
        extra={"backend": client.backend, "chat_model": settings.chat_model},
    )

    pool: Pool = AsyncConnectionPool(str(settings.database_url), open=False)
    await pool.open(wait=True)
    app.state.pool = pool
    app.state.chat_service = ChatService(pool, client, settings.chat_model)
    try:
        yield
    finally:
        logger.info("stopping")
        await pool.close()


def create_app() -> FastAPI:
    app = FastAPI(title="llm-stack API", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.add_middleware(RequestContext)
    app.add_exception_handler(
        ConversationNotFoundError, problems.conversation_not_found
    )
    app.add_exception_handler(RequestValidationError, problems.validation_failed)
    app.include_router(routes.router)

    return app


app = create_app()
