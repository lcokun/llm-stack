"""Behaviour that is FakeClient's alone. The shared contract lives in
test_inference_contract.py, which runs against every backend."""

import math
from collections.abc import AsyncIterator

from llm_stack_core.inference.base import (
    Capabilities,
    Message,
)
from llm_stack_core.inference.fake import EMBEDDING_DIMENSIONS, FakeClient


async def collect(stream: AsyncIterator[str]) -> list[str]:
    return [fragment async for fragment in stream]


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


async def test_embed_returns_one_unit_vector_per_text():
    vectors = await FakeClient().embed(["alpha", "beta"], "fake-embed")
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == EMBEDDING_DIMENSIONS
        assert math.isclose(sum(value * value for value in vector), 1.0, rel_tol=1e-9)


async def test_capabilities_describes_the_model():
    assert await FakeClient().capabilities("fake-vision") == Capabilities(
        vision=True, tools=True, embedding_dimensions=None
    )
