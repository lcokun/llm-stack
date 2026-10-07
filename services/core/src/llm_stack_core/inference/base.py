"""The inference boundary.

Everything above this module talks to models through 'InferenceClient'.
Nothing in here knows about HTTP, Ollama, or any particular backend.
"""

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """One turn in a conversation, as the moddel sees it."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a model can do, as declared by the backend."""

    vision: bool
    tools: bool
    embedding_dimensions: int | None


class InferenceBackendError(Exception):
    """The backend could not serve the request."""


class UnknownModelError(InferenceBackendError):
    """The requested model is not available from this backend."""


@runtime_checkable
class InferenceClient(Protocol):
    """The seam between the orchestration and whatever serves the models."""

    backend: ClassVar[str]
    """Which backend this is. A metric label, so keep it short and stable."""

    def chat(self, messages: Sequence[Message], model: str) -> AsyncGenerator[str]:
        """Stream the assistant's reply as text fragments."""
        ...

    async def embed(self, texts: Sequence[str], model: str) -> list[list[float]]:
        """Embed each text, returning one vector per input, in order."""
        ...

    async def capabilities(self, model: str) -> Capabilities:
        """Describe what 'model' supports."""
        ...
