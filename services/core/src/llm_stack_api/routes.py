"""HTTP routes. Translates between the wire format and core."""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from llm_stack_api.dependencies import Chat, Store
from llm_stack_api.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
)
from llm_stack_core.conversations.store import ConversationNotFoundError

SSE_MEDIA_TYPE = "text/event-stream"

router = APIRouter()


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: CreateConversationRequest, store: Store
) -> ConversationResponse:
    conversation = await store.create(body.title)
    return ConversationResponse.model_validate(conversation)


@router.get("/conversations/{id}")
async def get_conversation(id: UUID, store: Store) -> ConversationResponse:
    conversation = await store.get(id)
    if conversation is None:
        raise ConversationNotFoundError(str(id))
    return ConversationResponse.model_validate(conversation)


@router.post("/conversations/{id}/messages")
async def create_message(
    id: UUID, body: CreateMessageRequest, chat: Chat
) -> StreamingResponse:
    stream = chat.send(id, body.content)

    # Pull the first fragment here, while a failure can still become a status
    # code. ConversationNotFoundError propagates to the 404 handler.
    try:
        first: str | None = await anext(stream)
    except StopAsyncIteration:
        first = None

    async def events() -> AsyncIterator[str]:
        try:
            if first is not None:
                yield _event({"type": "delta", "delta": first})
            async for fragment in stream:
                yield _event({"type": "delta", "delta": fragment})
        except Exception as error:
            yield _event(
                {
                    "type": "error",
                    "problem": {
                        "type": "about:blank",
                        "title": "Generation failed",
                        "status": 500,
                        "detail": str(error),
                    },
                }
            )
            return
        finally:
            await stream.aclose()
        yield _event({"type": "done"})

    return StreamingResponse(events(), media_type=SSE_MEDIA_TYPE)
