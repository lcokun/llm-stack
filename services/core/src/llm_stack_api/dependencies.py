"""Wiring between the app's lifespan state and the route handlers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from llm_stack_core.chat import ChatService
from llm_stack_core.conversations.store import ConversationStore


async def get_store(request: Request) -> AsyncIterator[ConversationStore]:
    """One connection, one transaction, per request."""
    async with request.app.state.pool.connection() as connection:
        yield ConversationStore(connection)


Store = Annotated[ConversationStore, Depends(get_store)]


def get_chat_service(request: Request) -> ChatService:
    """The service built during startup, stored on app state."""
    return request.app.state.chat_service


Chat = Annotated[ChatService, Depends(get_chat_service)]
