import json
from uuid import uuid4

import httpx


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
