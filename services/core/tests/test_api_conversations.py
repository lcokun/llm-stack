from uuid import uuid4

import httpx


async def test_create_returns_201_and_the_conversation(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/conversations", json={"title": "first"})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "first"
    assert body["messages"] == []


async def test_title_may_be_omitted(client: httpx.AsyncClient) -> None:
    response = await client.post("/conversations", json={})

    assert response.status_code == 201
    assert response.json()["title"] is None


async def test_get_returns_the_conversation(client: httpx.AsyncClient) -> None:
    created = (await client.post("/conversations", json={})).json()

    response = await client.get(f"/conversations/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_unknown_conversation_is_a_problem_document(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"/conversations/{uuid4()}")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 404


async def test_a_malformed_id_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/conversations/not-a-uuid")

    assert response.status_code == 422
