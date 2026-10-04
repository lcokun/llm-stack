"""RFC 9457 problem responses."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem(status: int, title: str, detail: str | None = None) -> JSONResponse:
    content: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
    }
    if detail is not None:
        content["detail"] = detail
    return JSONResponse(
        status_code=status, media_type=PROBLEM_MEDIA_TYPE, content=content
    )


async def conversation_not_found(request: Request, exc: Exception) -> JSONResponse:
    return problem(404, "Conversation not found", str(exc))
