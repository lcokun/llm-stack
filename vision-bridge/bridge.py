"""Vision Bridge - transparent proxy that chains vision + abliterated models"""

import json
import os

from aiohttp import web, ClientSession

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
VISION_MODEL = os.environ.get("VISION_MODEL", "llama3.2-vision:11b")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "mannix/llama3.1-8b-abliterated")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "11435"))

async def call_vision_model(session: ClientSession, messages: list) -> str:
    """Send messages (with images) to the vision model, return its text response."""
    payload = {
        "model": VISION_MODEL,
        "messages": messages,
        "stream": False,
    }
    async with session.post(f"{OLLAMA_URL}/api/chat", json=payload) as resp:
        result = await resp.json()
        return result["message"]["content"]

def find_last_user_message(messages: list) -> dict | None:
    """Return the last message with role 'user', or None."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg
    return None

async def handle_chat(request: web.Request) -> web.StreamResponse:
    """Core endpoint - detect images, chain models, stream response."""
    body = await request.json()
    messages = body.get("messages", [])
    last_user = find_last_user_message(messages)

    if last_user and last_user.get("images"):
        # --- Image detected: call vision model first ---
        print(f"Image detected, calling vision model ({VISION_MODEL})...")

        vision_messages = [
            {"role": "user", "content": last_user["content"], "images": last_user["images"]}
        ]

        async with ClientSession() as session:
            description = await call_vision_model(session, vision_messages)

        print(f"Vision description: {description[:120]}...")

        # Strip images and prepend the description
        last_user.pop("images")
        last_user["content"] = (
            f"[Image description: {description}]\n\n{last_user['content']}"
        )

    # --- Forward to abliterated model (streaming) ---
    body["model"] = CHAT_MODEL

    stream_response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "application/x-ndjson"},
    )
    await stream_response.prepare(request)

    async with ClientSession() as session:
        async with session.post(
            f"{OLLAMA_URL}/api/chat", json=body
        ) as ollama_resp:
            async for chunk in ollama_resp.content.iter_any():
                await stream_response.write(chunk)

    await stream_response.write_eof()
    return stream_response

async def passthrough(request: web.Request) -> web.Response:
    """Catch-all: forward any other request to Ollama unchanged."""
    path = request.match_info.get("path", "")
    url = f"{OLLAMA_URL}/{path}"

    body = await request.read()

    headers = {}
    if "Content-Type" in request.headers:
        headers["Content-Type"] = request.headers["Content-Type"]

    async with ClientSession() as session:
        async with session.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body if body else None,
        ) as resp:
            # For streaming responses, pipe them through
            if resp.headers.get("Transfer-Encoding") == "chunked":
                stream_response = web.StreamResponse(
                    status=resp.status,
                    headers={"Content-Type": resp.headers.get("Content-Type", "application/json")},
                    
                )
                await stream_response.prepare(request)
                async for chunk in resp.content.iter_any():
                    await stream_response.write(chunk)
                await stream_response.write_eof()
                return stream_response

            # For normal responses, just forward the body
            resp_body = await resp.read()
            return web.Response(
                status=resp.status,
                body=resp_body,
                headers={"Content-Type": resp.headers.get("Content-Type", "application/json")},
            )

def main():
    app = web.Application(client_max_size=50 * 1024 * 1024)  # 50 MB
    
    # Specific route first, catch-all second
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_route("*", "/{path:.*}", passthrough)

    print(f"Vision Bridge starting on port {BRIDGE_PORT}")
    print(f"  Ollama URL:   {OLLAMA_URL}")
    print(f"  Vision model: {VISION_MODEL}")
    print(f"  Chat model:   {CHAT_MODEL}")

    web.run_app(app, host="0.0.0.0", port=BRIDGE_PORT)


if __name__ == "__main__":
    main()
