"""HTTP routes. Translates between the wire format and core."""

from uuid import UUID

from fastapi import APIRouter, status

from llm_stack_api.dependencies import Store
from llm_stack_api.schemas import ConversationResponse, CreateConversationRequest
from llm_stack_core.conversations.store import ConversationNotFoundError

router = APIRouter()


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
