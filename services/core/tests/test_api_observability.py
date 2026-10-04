"""Request correlation, access logging, and honest metric labels."""

import logging
from uuid import UUID, uuid4

import httpx
import pytest

from llm_stack_api.middleware import UNMATCHED_ROUTE

MIDDLEWARE_LOGGER = "llm_stack_api.middleware"
PROMETHEUS_MEDIA_TYPE = "text/plain"


async def test_metrics_serves_the_prometheus_exposition_format(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(PROMETHEUS_MEDIA_TYPE)
    assert "http_requests_total" in response.text


async def test_the_route_label_is_the_template_not_the_path(
    client: httpx.AsyncClient,
) -> None:
    conversation = (await client.post("/conversations", json={})).json()
    await client.get(f"/conversations/{conversation['id']}")

    body = (await client.get("/metrics")).text

    assert 'route="/conversations/{id}"' in body
    assert conversation["id"] not in body


async def test_unmatched_paths_share_a_single_label(client: httpx.AsyncClient) -> None:
    await client.get(f"/no-such-route-{uuid4()}")

    body = (await client.get("/metrics")).text

    assert f'route="{UNMATCHED_ROUTE}"' in body


async def test_an_incoming_request_id_is_echoed_back(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/healthz", headers={"x-request-id": "abc-123"})

    assert response.headers["x-request-id"] == "abc-123"


async def test_a_request_id_is_generated_when_the_client_sends_none(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/healthz")

    UUID(response.headers["x-request-id"])


async def test_each_request_logs_exactly_one_access_line(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=MIDDLEWARE_LOGGER):
        await client.get("/healthz")

    records = [record for record in caplog.records if record.name == MIDDLEWARE_LOGGER]
    assert len(records) == 1

    logged = vars(records[0])
    assert logged["method"] == "GET"
    assert logged["route"] == "/healthz"
    assert logged["status"] == 200
    assert logged["duration_ms"] >= 0
