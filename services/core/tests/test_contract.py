"""Responses must match api/openapi.yaml. The spec is the contract, not a description."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yaml
from jsonschema import Draft202012Validator

SPEC_PATH = Path(__file__).resolve().parents[3] / "api" / "openapi.yaml"
SPEC: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())


def _matches(schema_name: str, instance: object) -> None:
    """Validate against a component schema, with $refs resolved from the whole spec."""
    Draft202012Validator(
        {**SPEC, "$ref": f"#/components/schemas/{schema_name}"}
    ).validate(instance)


async def test_created_conversation_matches_the_contract(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/conversations", json={"title": "first"})

    _matches("Conversation", response.json())


async def test_fetched_conversation_matches_the_contract(
    client: httpx.AsyncClient,
) -> None:
    created = (await client.post("/conversations", json={})).json()
    await client.post(
        f"/conversations/{created['id']}/messages", json={"content": "hello"}
    )

    response = await client.get(f"/conversations/{created['id']}")

    _matches("Conversation", response.json())


async def test_not_found_matches_the_problem_schema(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/conversations/{uuid4()}")

    assert response.status_code == 404
    _matches("Problem", response.json())


async def test_validation_failure_matches_the_problem_schema(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/conversations", json={"title": "x" * 500})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    _matches("Problem", response.json())


async def test_stream_events_match_the_contract(client: httpx.AsyncClient) -> None:
    conversation = (await client.post("/conversations", json={})).json()

    response = await client.post(
        f"/conversations/{conversation['id']}/messages", json={"content": "hello"}
    )

    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.strip().split("\n\n")
        if line.startswith("data: ")
    ]
    assert events
    for event in events:
        _matches("ChatEvent", event)
