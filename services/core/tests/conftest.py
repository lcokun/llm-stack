"""Fixtures for tests that touch the database.

Every test runs inside a transaction that is rolled back afterwards, so
tests leave no rows behind and never observe each other's writes.
Requires a running database: `just dev`.
"""

import os
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from asgi_lifespan import LifespanManager
from psycopg import AsyncConnection
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from llm_stack_api.app import create_app
from llm_stack_core.config import get_settings
from llm_stack_core.conversations.store import ConversationStore

Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]


def pytest_configure() -> None:
    """Tests always run against FakeClient, whatever .env names.

    `just test` loads .env, so a developer pointed at Ollama would otherwise
    run the whole suite against a GPU model: slow, non-deterministic, and
    impossible on a CI runner.
    """
    os.environ["INFERENCE_BACKEND"] = "fake"
    os.environ["CHAT_MODEL"] = "fake-chat"
    os.environ["EMBEDDING_MODEL"] = "fake-embed"
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    conn = await AsyncConnection.connect(str(get_settings().database_url))
    try:
        yield conn
    finally:
        await conn.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def store(connection: AsyncConnection) -> ConversationStore:
    return ConversationStore(connection)


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[Pool]:
    pool: Pool = AsyncConnectionPool(str(get_settings().database_url), open=False)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        async with pool.connection() as connection:
            await connection.execute("truncate conversations cascade")
        await pool.close()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            try:
                yield client
            finally:
                async with app.state.pool.connection() as connection:
                    await connection.execute("truncate conversations cascade")
