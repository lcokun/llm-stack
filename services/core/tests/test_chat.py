from contextlib import aclosing
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from llm_stack_core.chat import ChatService, ConversationNotFoundError
from llm_stack_core.conversations.store import ConversationStore
from llm_stack_core.inference.fake import FakeClient


def _service(pool: AsyncConnectionPool) -> ChatService:
    return ChatService(pool, FakeClient(), "fake-chat")


async def _messages(
    pool: AsyncConnectionPool, conversation_id
) -> list[tuple[str, str]]:
    async with pool.connection() as connection:
        conversation = await ConversationStore(connection).get(conversation_id)
    assert conversation is not None
    return [(m.role, m.content) for m in conversation.messages]


async def test_send_streams_and_persists_both_messages(
    pool: AsyncConnectionPool,
) -> None:
    async with pool.connection() as connection:
        conversation = await ConversationStore(connection).create()

    fragments = [f async for f in _service(pool).send(conversation.id, "hello")]

    assert "".join(fragments) == "You said: hello"
    assert await _messages(pool, conversation.id) == [
        ("user", "hello"),
        ("assistant", "You said: hello"),
    ]


async def test_history_accumulates_across_turns(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as connection:
        conversation = await ConversationStore(connection).create()

    service = _service(pool)
    async for _ in service.send(conversation.id, "first"):
        pass
    async for _ in service.send(conversation.id, "second"):
        pass

    roles = [role for role, _ in await _messages(pool, conversation.id)]
    assert roles == ["user", "assistant", "user", "assistant"]


async def test_unknown_conversation_is_rejected(pool: AsyncConnectionPool) -> None:
    with pytest.raises(ConversationNotFoundError):
        async for _ in _service(pool).send(uuid4(), "hello"):
            pass


async def test_partial_reply_is_persisted_when_the_consumer_stops(
    pool: AsyncConnectionPool,
) -> None:
    async with pool.connection() as connection:
        conversation = await ConversationStore(connection).create()

    async with aclosing(_service(pool).send(conversation.id, "hello")) as stream:
        async for _ in stream:
            break

    stored = await _messages(pool, conversation.id)
    assert stored[0] == ("user", "hello")
    assert stored[1][0] == "assistant"
    assert stored[1][1] == "You said"
    assert stored[1][1] != "You said: hello"
