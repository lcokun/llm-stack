import pytest
from pydantic import ValidationError

from llm_stack_core.config import Settings


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]


def test_rejects_an_unknown_inference_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@127.0.0.1:5432/db")
    monkeypatch.setenv("INFERENCE_BACKEND", "olama")
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]
