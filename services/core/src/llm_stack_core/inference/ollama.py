"""An 'InferenceClient' backed by a local Ollama server.

Ollama streams NDJSON, one JSON object per line, rather than SSE. That
translation stops here: nothing above this module knows the wire format.
"""

import json
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from llm_stack_core.inference.base import (
    Capabilities,
    InferenceBackendError,
    Message,
    UnknownModelError,
)

CHAT_PATH = "/api/chat"
EMBED_PATH = "/api/embed"
SHOW_PATH = "/api/show"

EMBEDDING_LENGTH_SUFFIX = ".embedding_length"
NOT_FOUND = 404

# A cold model spends seconds loading before the first token, and a long reply
# streams for minutes. httpx defaults to five seconds for all of it.
TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)


class OllamaError(InferenceBackendError):
    """Ollama was unreachable, rejected the request, or answered unexpectedly."""


@dataclass(frozen=True, slots=True)
class _ModelFacts:
    """What '/api/show' reports about one model."""

    capabilities: Capabilities
    thinking: bool


class OllamaClient:
    """Talks to the Ollama HTTP API, asking about each model only once."""

    backend: ClassVar[str] = "ollama"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._facts_by_model: dict[str, _ModelFacts] = {}

    async def chat(
        self, messages: Sequence[Message], model: str
    ) -> AsyncGenerator[str]:
        if not messages:
            raise ValueError("chat requires at least one message")

        facts = await self._facts(model)
        if facts.capabilities.embedding_dimensions is not None:
            raise ValueError(f"{model} is an embedding model and cannot chat")

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        if facts.thinking:
            # Reasoning then arrives in message.thinking rather than leaking
            # into message.content, which is what gets streamed to the caller.
            payload["think"] = True

        try:
            async with self._http.stream("POST", CHAT_PATH, json=payload) as response:
                await self._check_stream(response, model)
                async for line in response.aiter_lines():
                    fragment = _fragment(line) if line else ""
                    if fragment:
                        yield fragment
        except httpx.RequestError as error:
            raise OllamaError(f"cannot reach ollama: {error}") from error

    async def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        facts = await self._facts(model)
        if facts.capabilities.embedding_dimensions is None:
            raise ValueError(f"{model} does not produce embeddings")
        if not texts:
            return []

        body = await self._post(
            EMBED_PATH, {"model": model, "input": list(texts)}, model
        )
        embeddings = body.get("embeddings")
        if embeddings is None:
            raise OllamaError(f"{EMBED_PATH} returned no embeddings")
        return embeddings

    async def capabilities(self, model: str) -> Capabilities:
        return (await self._facts(model)).capabilities

    async def _facts(self, model: str) -> _ModelFacts:
        """Ask once per model. Capabilities do not change while we run."""
        if model not in self._facts_by_model:
            body = await self._post(SHOW_PATH, {"model": model}, model)
            self._facts_by_model[model] = _read_facts(body)
        return self._facts_by_model[model]

    async def _post(
        self, path: str, payload: dict[str, Any], model: str
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(path, json=payload)
        except httpx.RequestError as error:
            raise OllamaError(f"cannot reach ollama: {error}") from error

        if response.status_code == NOT_FOUND:
            raise UnknownModelError(model)
        if response.is_error:
            raise OllamaError(
                f"{path} returned {response.status_code}: {response.text}"
            )
        return response.json()

    async def _check_stream(self, response: httpx.Response, model: str) -> None:
        """Turn an error status into an exception before reading any chunks."""
        if not response.is_error:
            return

        await response.aread()
        if response.status_code == NOT_FOUND:
            raise UnknownModelError(model)
        raise OllamaError(
            f"{CHAT_PATH} returned {response.status_code}: {response.text}"
        )


def _fragment(line: str) -> str:
    """The text in one NDJSON chunk. Empty for chunks carrying no content."""
    try:
        chunk: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError as error:
        raise OllamaError(f"ollama sent a malformed chunk: {line!r}") from error

    reported = chunk.get("error")
    if reported:
        raise OllamaError(str(reported))

    return chunk.get("message", {}).get("content", "")


def _read_facts(body: dict[str, Any]) -> _ModelFacts:
    declared = set(body.get("capabilities", ()))
    model_info: dict[str, Any] = body.get("model_info", {})
    return _ModelFacts(
        capabilities=Capabilities(
            vision="vision" in declared,
            tools="tools" in declared,
            embedding_dimensions=(
                _embedding_length(model_info) if "embedding" in declared else None
            ),
        ),
        thinking="thinking" in declared,
    )


def _embedding_length(model_info: dict[str, Any]) -> int | None:
    """The key is architecture-prefixed, as in 'nomic-bert.embedding_length'."""
    for key, value in model_info.items():
        if key.endswith(EMBEDDING_LENGTH_SUFFIX):
            return int(value)
    return None
