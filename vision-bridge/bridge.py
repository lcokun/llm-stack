"""Vision Bridge - transparent proxy that chains vision + abliterated models"""

import json
import os
import tempfile
from urllib.parse import quote_plus

from aiohttp import web, ClientSession

from ingest import ingest_file, get_embedding, collection

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
VISION_MODEL = os.environ.get("VISION_MODEL", "llama3.2-vision:11b")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "mannix/llama3.1-8b-abliterated")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "11435"))
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")

async def search_searxng(session: ClientSession, query: str) -> str:
    """Query SearXNG and return formatted results."""
    url = f"{SEARXNG_URL}/search?q={quote_plus(query)}&format=json"
    async with session.get(url) as resp:
        data = await resp.json()

    results = data.get("results", [])[:5]
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        link = r.get("url", "")
        snippet = r.get("content", "")
        lines.append(f"{i}. {title}\n   {link}\n   {snippet}")
    return "\n\n".join(lines)


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

    if last_user and isinstance(last_user.get("content"), str) and last_user["content"].startswith("/ingest "):
        # --- Ingest: parse file and store in ChromaDB ---
        file_path = last_user["content"][len("/ingest "):].strip()
        if not file_path.startswith("/"):
            file_path = "/" + file_path
        print(f"Ingest detected, processing: {file_path}")

        try:
            count = await ingest_file(file_path, OLLAMA_URL)
            msg = f"Ingested {file_path} ({count} chunks stored in ChromaDB)."
            print(msg)
        except Exception as e:
            msg = f"Ingest failed: {e}"
            print(msg)

        # Return a direct response instead of forwarding to chat model
        response_body = json.dumps({
            "model": CHAT_MODEL,
            "message": {"role": "assistant", "content": msg},
            "done": True,
        })
        return web.Response(
            status=200,
            body=response_body + "\n",
            content_type="application/x-ndjson",
        )

    if last_user and isinstance(last_user.get("content"), str) and last_user["content"].startswith("/rag "):
        # --- RAG: embed query, search ChromaDB, inject context ---
        query = last_user["content"][len("/rag "):].strip()
        print(f"RAG detected, searching ChromaDB for: {query}")

        async with ClientSession() as session:
            query_embedding = await get_embedding(session, query, OLLAMA_URL)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=5,
        )

        docs = results["documents"][0]
        if docs:
            context = "\n\n---\n\n".join(docs)
            last_user["content"] = (
                f"[Relevant documents:\n{context}]\n\n{query}"
            )
            print(f"RAG: injected {len(docs)} chunks into context")
        else:
            print("RAG: no matching documents found")

    if last_user and isinstance(last_user.get("content"), str) and last_user["content"].startswith("/search "):
        # --- Search detected: query SearXNG ---
        query = last_user["content"][len("/search "):].strip()
        print(f"Search detected, querying SearXNG for: {query}")

        async with ClientSession() as session:
            search_results = await search_searxng(session, query)

        print(f"Search results: {search_results[:120]}...")

        last_user["content"] = (
            f"[Web search results for '{query}':\n{search_results}]\n\n{query}"
        )

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

ALLOWED_MODELS = {VISION_MODEL, CHAT_MODEL}

async def handle_tags(request: web.Request) -> web.Response:
    """Filter /api/tags to only show the vision and chat models."""
    async with ClientSession() as session:
        async with session.get(f"{OLLAMA_URL}/api/tags") as resp:
            data = await resp.json()

    def matches_allowed(name: str) -> bool:
        return name in ALLOWED_MODELS or name.rsplit(":", 1)[0] in ALLOWED_MODELS

    data["models"] = [
        m for m in data.get("models", [])
        if matches_allowed(m.get("name", "")) or matches_allowed(m.get("model", ""))
    ]
    return web.json_response(data)


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

async def handle_upload(request: web.Request) -> web.Response:
    """Accept a multipart file upload and ingest it into ChromaDB"""
    reader = await request.multipart()
    part = await reader.next()

    if part is None or part.filename is None:
        return web.json_response({"error": "No file uploaded"}, status=400)

    filename = part.filename
    print(f"Upload received: {filename}")

    # Write to temp file, preserving the extension for ingest_file's format check
    suffix = os.path.splitext(filename)[1]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        while True:
            chunk = await part.read_chunk()
            if not chunk:
                break
            tmp.write(chunk)
        tmp.close()

        count = await ingest_file(tmp.name, OLLAMA_URL)
        return web.json_response({"status": "ok", "file": filename, "chunks": count})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    finally:
        os.unlink(tmp.name)

def main():
    app = web.Application(client_max_size=50 * 1024 * 1024)  # 50 MB
    
    # Specific route first, catch-all second
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_get("/api/tags", handle_tags)
    app.router.add_post("/api/ingest", handle_upload)
    app.router.add_route("*", "/{path:.*}", passthrough)

    print(f"Vision Bridge starting on port {BRIDGE_PORT}")
    print(f"  Ollama URL:   {OLLAMA_URL}")
    print(f"  Vision model: {VISION_MODEL}")
    print(f"  Chat model:   {CHAT_MODEL}")
    print(f"  SearXNG URL:  {SEARXNG_URL}")

    web.run_app(app, host="0.0.0.0", port=BRIDGE_PORT)


if __name__ == "__main__":
    main()
