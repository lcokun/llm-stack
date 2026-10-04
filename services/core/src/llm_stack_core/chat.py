"""Chat orchestration: persist, prompt, stream, persist.

Owns connection lifetime deliberately. No connection is held while the model
streams, because a reply takes seconds and a pooled connection held that long
starves every other request.
"""

import time
from collections.abc import AsyncGenerator, Sequence
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from llm_stack_core.conversations.store import (
    ConversationNotFoundError,
    ConversationStore,
)
from llm_stack_core.inference.base import InferenceClient
from llm_stack_core.inference.base import Message as PrompMessage
from llm_stack_core.observability import (
    inference_requests,
    inference_stream_duration,
    inference_time_to_first_fragment,
)


class ChatService:
    """Turns a user message into a streamed reply, persisting both ends."""

    def __init__(
        self, pool: AsyncConnectionPool, client: InferenceClient, model: str
    ) -> None:
        self._pool = pool
        self._client = client
        self._model = model

    async def send(self, conversation_id: UUID, content: str) -> AsyncGenerator[str]:
        """Stream the assistant's reply, persisting it even if the stream ends early"""
        history = await self._record_user_message(conversation_id, content)

        backend = self._client.backend
        fragments: list[str] = []
        outcome = "error"
        started = time.perf_counter()
        try:
            async for fragment in self._client.chat(history, self._model):
                if not fragments:
                    inference_time_to_first_fragment.labels(
                        backend, self._model
                    ).observe(time.perf_counter() - started)
                fragments.append(fragment)
                yield fragment
            outcome = "ok"
        except GeneratorExit:
            outcome = "cancelled"
            raise
        finally:
            inference_stream_duration.labels(backend, self._model).observe(
                time.perf_counter() - started
            )
            inference_requests.labels(backend, self._model, outcome).inc()
            if fragments:
                await self._record_assistant_message(
                    conversation_id, "".join(fragments)
                )

    async def _record_user_message(
        self, conversation_id: UUID, content: str
    ) -> Sequence[PrompMessage]:
        async with self._pool.connection() as connection:
            store = ConversationStore(connection)
            conversation = await store.get(conversation_id)
            if conversation is None:
                raise ConversationNotFoundError(str(conversation_id))
            stored = await store.add_message(conversation_id, "user", content)

        return [message.to_prompt() for message in conversation.messages] + [
            stored.to_prompt()
        ]

    async def _record_assistant_message(
        self, conversation_id: UUID, content: str
    ) -> None:
        async with self._pool.connection() as connection:
            await ConversationStore(connection).add_message(
                conversation_id, "assistant", content
            )
