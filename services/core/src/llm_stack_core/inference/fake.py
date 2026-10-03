"""An in-process 'InferenceClient' for development and CI.

Deterministic and dependency-free: no network, no GPU, no Ollama. The same
input always produces the same output, so tests can assert on it.
"""

import hashlib
import math
import random
from collections.abc import AsyncGenerator, Sequence

from llm_stack_core.inference.base import Capabilities, Message, UnknownModelError

FRAGMENT_SIZE = 8
EMBEDDING_DIMENSIONS = 768

_MODELS: dict[str, Capabilities] = {
    "fake-chat": Capabilities(vision=False, tools=False, embedding_dimensions=None),
    "fake-vision": Capabilities(vision=True, tools=True, embedding_dimensions=None),
    "fake-embed": Capabilities(
        vision=False, tools=False, embedding_dimensions=EMBEDDING_DIMENSIONS
    ),
}


class FakeClient:
    """Echoes the last message back, one fragment at a time."""

    async def chat(
        self, messages: Sequence[Message], model: str
    ) -> AsyncGenerator[str]:
        if self._lookup(model).embedding_dimensions is not None:
            raise ValueError(f"{model} is an embedding model and cannot chat")
        if not messages:
            raise ValueError("chat requires at least one message")

        reply = f"You said: {messages[-1].content}"
        for start in range(0, len(reply), FRAGMENT_SIZE):
            yield reply[start : start + FRAGMENT_SIZE]

    async def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        dimensions = self._lookup(model).embedding_dimensions
        if dimensions is None:
            raise ValueError(f"{model} does not produce embeddings")
        return [_unit_vector(text, dimensions) for text in texts]

    async def capabilities(self, model: str) -> Capabilities:
        return self._lookup(model)

    def _lookup(self, model: str) -> Capabilities:
        try:
            return _MODELS[model]
        except KeyError:
            raise UnknownModelError(model) from None


def _unit_vector(text: str, dimensions: int) -> list[float]:
    """A stable pseudo-random unit vector derived from 'text'."""

    seed = int.from_bytes(hashlib.sha256(text.encode()).digest(), "big")
    rng = random.Random(seed)
    raw = [rng.gauss(0.0, 1.0) for _ in range(dimensions)]
    length = math.sqrt(sum(value * value for value in raw))
    return [value / length for value in raw]
