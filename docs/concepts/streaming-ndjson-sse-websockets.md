# Streaming: NDJSON, SSE and WebSockets

**Short version:** token streaming is one-directional, so SSE is the right tool.
WebSockets solve a problem this stack does not have.

## Why stream at all

A model generates tokens one at a time. Waiting for the full response before showing
anything means staring at nothing for ten seconds. Streaming turns the same total latency
into an immediate trickle, which feels dramatically faster even though it finishes at
exactly the same moment. Perceived latency is what you are buying.

## The three options

### NDJSON, what v1 used

Newline-delimited JSON: one JSON object per line, sent as the response body arrives.

```
{"message":{"content":"Hel"},"done":false}
{"message":{"content":"lo"},"done":false}
{"done":true}
```

Ollama's API speaks this, which is why v1's bridge did:

```python
async for chunk in ollama_resp.content.iter_any():
    await stream_response.write(chunk)
```

It is a perfectly good wire format and trivial to produce. Its weakness is on the client,
where there is no browser API for it. You get a `ReadableStream` and split on newlines
yourself, including the case where a chunk boundary lands mid-line. That is a real bug
source: a buffer arriving as `{"content":"He` and `llo"}` must be reassembled before
parsing.

### SSE, what v2 uses

Server-Sent Events. A standard, declared by `Content-Type: text/event-stream`:

```
data: {"delta":"Hel"}

data: {"delta":"lo"}

data: [DONE]

```

Each event is `data: ` plus a payload, terminated by a blank line. What the standard buys:

- framing is handled. `EventSource` (or a `fetch` reader) hands you complete events, with
  no partial-line reassembly.
- automatic reconnection, with `Last-Event-ID` so the server can resume.
- proxy friendliness. It is ordinary HTTP, so it passes through reverse proxies, TLS
  terminators and corporate middleboxes that mangle protocol upgrades. Relevant with Caddy
  in front and Tailscale in the path.
- it is what the ecosystem speaks. OpenAI's streaming API is SSE, so the
  OpenAI-compatible endpoint from
  [ADR 0006](../decisions/0006-own-api-plus-openai-compat.md) requires it anyway.

One gotcha worth knowing: proxies that buffer responses will hold your events and deliver
them in a clump, which looks exactly like the stream being broken. `X-Accel-Buffering: no`
and disabling proxy buffering is a standard part of deploying SSE.

### WebSockets, not used here

A protocol upgrade giving a persistent bidirectional channel. Genuinely necessary when
the *client* also needs to push at arbitrary times: collaborative editing, multiplayer,
live cursors, chat between humans.

Token streaming is one-directional. The client sends one request and then only listens.
Paying for a bidirectional protocol buys nothing and costs plenty: no automatic
reconnection, no plain-HTTP semantics, worse proxy compatibility, its own auth story
because headers work differently on upgrade, and connection state to manage on the server.

Reach for WebSockets when the client needs to speak mid-stream. Cancelling a generation is
not that case, since it is a `DELETE` to another endpoint.

## Where the translation lives

Ollama speaks NDJSON. Browsers want SSE. So something must translate, and the natural
home is the gateway:

```
Ollama ──NDJSON──▶ core ──NDJSON──▶ gateway ──SSE──▶ browser
```

Reading lines, parsing them, and re-emitting them as SSE frames is a concrete, well-scoped
job for the Go gateway in phase 2, and a good first task in a new language. It is also the
right boundary. The gateway is already the edge that owns HTTP concerns, auth and metrics,
so protocol translation belongs there rather than in `core`, which should not know what
shape its caller wants.

## Things that bite when streaming

Errors mid-stream are the awkward one. Once you have sent `200 OK` and started writing,
you cannot change the status code, so a failure after the first token has to be delivered
*inside* the stream as an error event, and the client has to handle a response that
started fine and ended badly. Design the event schema for this from the start, because it
covers every timeout and every OOM.

Flushing matters because buffered output defeats the entire purpose. The app, the
framework and the reverse proxy all have to flush per event.

Cancellation: if the user closes the tab, the model should stop generating rather than
burning GPU on tokens nobody will read. That means propagating disconnection from the
browser, through the gateway, through core, to the Ollama request. It is easy to get wrong
in a way nothing notices until the GPU is busy with abandoned work.

Token accounting has to be accumulated across the stream and recorded at the end,
including when the stream ends badly. A request that failed halfway still consumed tokens.
