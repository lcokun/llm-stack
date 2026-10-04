"""The InferenceClient contract, asserted against every backend.

Ollama is skipped when nothing answers on its port, so CI runs the fake
alone and a developer with a model loaded gets both. Model names come from
the environment rather than Settings, because conftest pins Settings to the
fake for the whole session.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache

import httpx
import pytest
import pytest_asyncio

from llm_stack_core.inference.base import (
    InferenceClient,
    Message,
    UnknownModelError,
)
from llm_stack_core.inference.fake import FakeClient
from llm_stack_core.inference.ollama import TIMEOUT, OllamaClient

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "qwen3:4b")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

SHORT_PROMPT = "Reply with one word: hello"


@dataclass(frozen=True, slots=True)
class Backend:
    """One client plus the model names it can actually serve."""

    client: InferenceClient
    chat_model: str
    embed_model: str


@lru_cache
def _ollama_is_up() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/version", timeout=1.0).is_success
    except httpx.RequestError:
        return False


@pytest_asyncio.fixture(params=["fake", "ollama"])
async def backend(request: pytest.FixtureRequest) -> AsyncIterator[Backend]:
    if request.param == "fake":
        yield Backend(FakeClient(), "fake-chat", "fake-embed")
        return

    if not _ollama_is_up():
        pytest.skip(f"no ollama on {OLLAMA_URL}")

    async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=TIMEOUT) as http:
        yield Backend(OllamaClient(http), OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL)


async def collect(stream: AsyncIterator[str]) -> list[str]:
    return [fragment async for fragment in stream]


async def test_satisfies_the_protocol(backend: Backend) -> None:
    assert isinstance(backend.client, InferenceClient)
    assert backend.client.backend


async def test_chat_streams_text_in_fragments(backend: Backend) -> None:
    fragments = await collect(
        backend.client.chat([Message("user", SHORT_PROMPT)], backend.chat_model)
    )

    assert fragments
    assert "".join(fragments).strip()


async def test_chat_defers_validation_until_iteration(backend: Backend) -> None:
    stream = backend.client.chat([], backend.chat_model)

    await stream.aclose()


async def test_chat_requires_a_message(backend: Backend) -> None:
    with pytest.raises(ValueError):
        await collect(backend.client.chat([], backend.chat_model))


async def test_chat_rejects_an_embedding_model(backend: Backend) -> None:
    with pytest.raises(ValueError):
        await collect(backend.client.chat([Message("user", "hi")], backend.embed_model))


async def test_embed_returns_one_vector_per_text(backend: Backend) -> None:
    vectors = await backend.client.embed(["alpha", "beta"], backend.embed_model)

    assert len(vectors) == 2
    assert len({len(vector) for vector in vectors}) == 1
    assert len(vectors[0]) > 0


async def test_embed_is_deterministic(backend: Backend) -> None:
    first = await backend.client.embed(["alpha"], backend.embed_model)
    second = await backend.client.embed(["alpha"], backend.embed_model)

    assert first == second


async def test_embed_distinguishes_texts(backend: Backend) -> None:
    alpha, beta = await backend.client.embed(["alpha", "beta"], backend.embed_model)

    assert alpha != beta


async def test_embed_rejects_a_chat_model(backend: Backend) -> None:
    with pytest.raises(ValueError):
        await backend.client.embed(["alpha"], backend.chat_model)


async def test_capabilities_reports_embedding_dimensions(backend: Backend) -> None:
    embedder = await backend.client.capabilities(backend.embed_model)
    chatter = await backend.client.capabilities(backend.chat_model)

    assert embedder.embedding_dimensions is not None
    assert embedder.embedding_dimensions > 0
    assert chatter.embedding_dimensions is None


async def test_unknown_model_raises(backend: Backend) -> None:
    with pytest.raises(UnknownModelError):
        await backend.client.capabilities("no-such-model-exists")
