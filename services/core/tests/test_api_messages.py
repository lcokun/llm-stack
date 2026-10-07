import json
from collections.abc import AsyncGenerator, Sequence
from typing import ClassVar
from uuid import uuid4

import httpx
from asgi_lifespan import LifespanManager
from psycopg_pool import AsyncConnectionPool

from llm_stack_api.app import create_app
from llm_stack_core.chat import ChatService
from llm_stack_core.inference.base import Capabilities, InferenceBackendError, Message

NDJSON = {"Accept": "application/x-ndjson"}


def _ndjson_events(body: str) -> list[dict]:
    return [json.loads(line) for line in body.splitlines() if line]


def _events(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.strip().split("\n\n")
        if line.startswith("data: ")
    ]


async def test_streams_deltas_then_done(client: httpx.AsyncClient) -> None:
    conversation = (await client.post("/conversations", json={})).json()

    response = await client.post(
        f"/conversations/{conversation['id']}/messages", json={"content": "hello"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert events[-1] == {"type": "done"}
    assert "".join(e["delta"] for e in events if e["type"] == "delta") == (
        "You said: hello"
    )


async def test_reply_is_persisted(client: httpx.AsyncClient) -> None:
    conversation = (await client.post("/conversations", json={})).json()

    await client.post(
        f"/conversations/{conversation['id']}/messages", json={"content": "hello"}
    )
    loaded = (await client.get(f"/conversations/{conversation['id']}")).json()

    assert [(m["role"], m["content"]) for m in loaded["messages"]] == [
        ("user", "hello"),
        ("assistant", "You said: hello"),
    ]


async def test_unknown_conversation_is_404_not_a_stream(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/conversations/{uuid4()}/messages", json={"content": "hello"}
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_empty_content_is_rejected(client: httpx.AsyncClient) -> None:
    conversation = (await client.post("/conversations", json={})).json()

    response = await client.post(
        f"/conversations/{conversation['id']}/messages", json={"content": ""}
    )

    assert response.status_code == 422


class UnreachableClient:
    """A backend that is down. Every call fails the way a refused connection does."""

    backend: ClassVar[str] = "unreachable"

    async def chat(
        self, messages: Sequence[Message], model: str
    ) -> AsyncGenerator[str]:
        raise InferenceBackendError("connection refused")
        yield  # never runs; makes this an async generator like the real clients

    async def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        raise InferenceBackendError("connection refused")

    async def capabilities(self, model: str) -> Capabilities:
        raise InferenceBackendError("connection refused")


async def test_unreachable_backend_is_a_502_problem(
    pool: AsyncConnectionPool,
) -> None:
    app = create_app()
    async with LifespanManager(app):
        app.state.chat_service = ChatService(pool, UnreachableClient(), "fake-chat")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            conversation = (await client.post("/conversations", json={})).json()
            response = await client.post(
                f"/conversations/{conversation['id']}/messages",
                json={"content": "hello"},
            )

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_streams_ndjson_when_asked(client: httpx.AsyncClient) -> None:
    conversation = (await client.post("/conversations", json={})).json()

    response = await client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "hello"},
        headers=NDJSON,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = _ndjson_events(response.text)
    assert events[-1] == {"type": "done"}
    assert "".join(e["delta"] for e in events if e["type"] == "delta") == (
        "You said: hello"
    )


async def test_unknown_conversation_is_404_in_ndjson_too(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/conversations/{uuid4()}/messages",
        json={"content": "hello"},
        headers=NDJSON,
    )

    assert response.status_code == 404
