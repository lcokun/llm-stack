"""Behavioural spec for FakeClient.

Most of these describe the InferenceClient contract rather than the fake,
so they should still apply when OllamaClient exists.
"""

import math

import pytest

from llm_stack_core.inference.base import (
    Capabilities,
    InferenceClient,
    Message,
    UnknownModelError,
)
from llm_stack_core.inference.fake import EMBEDDING_DIMENSIONS, FakeClient


async def collect(stream) -> list[str]:
    return [fragment async for fragment in stream]


def test_satisfies_the_protocol():
    assert isinstance(FakeClient(), InferenceClient)


async def test_chat_streams_the_reply_in_fragments():
    fragments = await collect(
        FakeClient().chat([Message("user", "hello")], "fake-chat")
    )
    assert "".join(fragments) == "You said: hello"
    assert len(fragments) > 1


async def test_chat_is_deterministic():
    messages = [Message("user", "hello")]
    first = await collect(FakeClient().chat(messages, "fake-chat"))
    second = await collect(FakeClient().chat(messages, "fake-chat"))
    assert first == second


async def test_chat_replies_to_the_last_message():
    messages = [
        Message("user", "first"),
        Message("assistant", "..."),
        Message("user", "second"),
    ]
    fragments = await collect(FakeClient().chat(messages, "fake-chat"))
    assert "".join(fragments) == "You said: second"


async def test_chat_defers_validation_until_iteration():
    stream = FakeClient().chat([], "fake-chat")
    await stream.aclose()


async def test_chat_requires_a_message():
    with pytest.raises(ValueError):
        await collect(FakeClient().chat([], "fake-chat"))


async def test_chat_rejects_an_embedding_model():
    with pytest.raises(ValueError):
        await collect(FakeClient().chat([Message("user", "hi")], "fake-embed"))


async def test_embed_returns_one_unit_vector_per_text():
    vectors = await FakeClient().embed(["alpha", "beta"], "fake-embed")
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == EMBEDDING_DIMENSIONS
        assert math.isclose(sum(value * value for value in vector), 1.0, rel_tol=1e-9)


async def test_embed_is_deterministic():
    first = await FakeClient().embed(["alpha"], "fake-embed")
    second = await FakeClient().embed(["alpha"], "fake-embed")
    assert first == second


async def test_embed_distinguishes_texts():
    alpha, beta = await FakeClient().embed(["alpha", "beta"], "fake-embed")
    assert alpha != beta


async def test_embed_rejects_a_chat_model():
    with pytest.raises(ValueError):
        await FakeClient().embed(["alpha"], "fake-chat")


async def test_capabilities_describes_the_model():
    assert await FakeClient().capabilities("fake-vision") == Capabilities(
        vision=True, tools=True, embedding_dimensions=None
    )


async def test_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        await FakeClient().capabilities("gpt-5")
