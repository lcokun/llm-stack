"""Reading and writing conversations. Knows SQL, knows nothing about HTTP."""

from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from llm_stack_core.conversations.models import Conversation, Message
from llm_stack_core.inference.base import Role

_INSERT_CONVERSATION = """
    insert into conversations (title)
    values (%s)
    returning id, title, created_at
"""

_SELECT_CONVERSATION = """
    select id, title, created_at
    from conversations
    where id = %s
"""

_SELECT_MESSAGES = """
    select id, conversation_id, role, content, created_at
    from messages
    where conversation_id = %s
    order by id
"""

_INSERT_MESSAGE = """
    insert into messages (conversation_id, role, content)
    values (%s, %s, %s)
    returning id, conversation_id, role, content, created_at
"""


class ConversationStore:
    """Conversation persistence over one connection, so one caller owns one transaction."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def create(self, title: str | None = None) -> Conversation:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(_INSERT_CONVERSATION, (title,))
            row = await cursor.fetchone()
        assert row is not None  # RETURNING on a successful insert always yields a row
        return Conversation(**row)

    async def get(self, conversation_id: UUID) -> Conversation | None:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(_SELECT_CONVERSATION, (conversation_id,))
            row = await cursor.fetchone()
            if row is None:
                return None
            await cursor.execute(_SELECT_MESSAGES, (conversation_id,))
            messages = tuple(Message(**m) for m in await cursor.fetchall())
        return Conversation(**row, messages=messages)

    async def add_message(
        self, conversation_id: UUID, role: Role, content: str
    ) -> Message:
        async with self._connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(_INSERT_MESSAGE, (conversation_id, role, content))
            row = await cursor.fetchone()
        assert row is not None
        return Message(**row)
