"""HTTP routes. Translates between the wire format and core."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, status
from fastapi.responses import StreamingResponse

from llm_stack_api.dependencies import Chat, Store
from llm_stack_api.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
)
from llm_stack_core.conversations.store import ConversationNotFoundError

SSE_MEDIA_TYPE = "text/event-stream"
NDJSON_MEDIA_TYPE = "application/x-ndjson"

router = APIRouter()


def _sse_line(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _ndjson_line(payload: dict[str, Any]) -> str:
    return f"{json.dumps(payload)}\n"


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
    id: UUID,
    body: CreateMessageRequest,
    chat: Chat,
    accept: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    wants_ndjson = accept is not None and NDJSON_MEDIA_TYPE in accept
    encode = _ndjson_line if wants_ndjson else _sse_line
    media_type = NDJSON_MEDIA_TYPE if wants_ndjson else SSE_MEDIA_TYPE

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
                yield encode({"type": "delta", "delta": first})
            async for fragment in stream:
                yield encode({"type": "delta", "delta": fragment})
        except Exception as error:
            yield encode(
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
        yield encode({"type": "done"})

    return StreamingResponse(events(), media_type=media_type)
