"""Request and response bodies. Mirrors api/openapi.yaml."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from llm_stack_core.inference.base import Role


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    role: Role
    content: str
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]
