from uuid import uuid4

import pytest
from psycopg import AsyncConnection
from psycopg.errors import CheckViolation, ForeignKeyViolation

from llm_stack_core.conversations.store import ConversationStore


async def test_create_returns_a_persisted_conversation(
    store: ConversationStore,
) -> None:
    conversation = await store.create(title="first")

    assert conversation.title == "first"
    assert conversation.messages == ()
    assert conversation.created_at is not None


async def test_title_is_optional(store: ConversationStore) -> None:
    conversation = await store.create()

    assert conversation.title is None


async def test_get_returns_none_for_an_unknown_id(store: ConversationStore) -> None:
    assert await store.get(uuid4()) is None


async def test_messages_come_back_in_insertion_order(
    store: ConversationStore,
) -> None:
    conversation = await store.create()
    for content in ("one", "two", "three"):
        await store.add_message(conversation.id, "user", content)

    loaded = await store.get(conversation.id)

    assert loaded is not None
    assert [m.content for m in loaded.messages] == ["one", "two", "three"]


async def test_message_converts_to_a_prompt_turn(store: ConversationStore) -> None:
    conversation = await store.create()
    message = await store.add_message(conversation.id, "user", "hello")

    prompt = message.to_prompt()

    assert prompt.role == "user"
    assert prompt.content == "hello"
    assert not hasattr(prompt, "id")


async def test_message_requires_an_existing_conversation(
    store: ConversationStore,
) -> None:
    with pytest.raises(ForeignKeyViolation):
        await store.add_message(uuid4(), "user", "orphan")


async def test_role_is_constrained(store: ConversationStore) -> None:
    conversation = await store.create()

    with pytest.raises(CheckViolation):
        await store.add_message(conversation.id, "moderator", "nope")  # type: ignore[arg-type]


async def test_deleting_a_conversation_removes_its_messages(
    store: ConversationStore, connection: AsyncConnection
) -> None:
    conversation = await store.create()
    await store.add_message(conversation.id, "user", "hello")

    await connection.execute(
        "delete from conversations where id = %s", (conversation.id,)
    )

    async with connection.cursor() as cursor:
        await cursor.execute(
            "select count(*) from messages where conversation_id = %s",
            (conversation.id,),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row[0] == 0
