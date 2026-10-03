"""Conversation and message rows, as stored."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from llm_stack_core.inference.base import Message as PromptMessage
from llm_stack_core.inference.base import Role


@dataclass(frozen=True, slots=True)
class Message:
    """One stored message row."""

    id: UUID
    conversation_id: UUID
    role: Role
    content: str
    created_at: datetime

    def to_prompt(self) -> PromptMessage:
        """Drop the storage fields the model has no use for."""
        return PromptMessage(role=self.role, content=self.content)


@dataclass(frozen=True, slots=True)
class Conversation:
    """A conversation and, when loaded, its messages in order."""

    id: UUID
    title: str | None
    created_at: datetime
    messages: tuple[Message, ...] = field(default_factory=tuple)
