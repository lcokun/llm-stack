"""Fixtures for tests that touch the database.

Every test runs inside a transaction that is rolled back afterwards, so
tests leave no rows behind and never observe each other's writes.
Requires a running database: `just dev`.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from llm_stack_core.config import get_settings
from llm_stack_core.conversations.store import ConversationStore

Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]


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
