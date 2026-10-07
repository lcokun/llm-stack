# 0009 — Core keeps an internal HTTP API behind the gateway

- **Status:** accepted
- **Date:** 2026-10-07

## Context

Phase 2 in PLAN.md says the Python API layer is deleted, `core` moves onto a bridge
network with no published port, and the gateway translates NDJSON to SSE. Read together,
the last two imply that something in `core` still answers over the network and streams
NDJSON, so "API layer deleted" can only mean the public layer. Nothing written down says
what remains, so the first line of proxy code would have decided it by accident.

`core/` is a library with no process of its own. The gateway is a separate process in a
separate language and needs a transport to reach `ChatService` and `ConversationStore`.
Today that transport is `llm_stack_api`: 343 lines of FastAPI that also own the public
contract, SSE framing, problem responses and request ids.

PLAN.md and the Consequences of ADR 0008 both say the Go client is generated from
`api/`. That was wrong. The gateway serves `api/openapi.yaml` and never calls it. What
the gateway calls is `core`, and this ADR amends 0008 on that point.

## Decision

`core` keeps a small internal HTTP API. The gateway is its only caller.

### Shape

The internal API mirrors the public routes: same paths, same JSON bodies. The one
difference is chat, which streams NDJSON (`application/x-ndjson`), one `ChatEvent` object
per line, with the same `delta`, `error` and `done` events the public API sends as SSE.
The gateway changes the framing and never reinterprets an event.

There is no separate spec for it yet. While the two APIs mirror each other, a second spec
would be a hand-maintained copy. The gateway talks to core through a small hand-written Go
client; a generated one would cover two calls, since the streaming call needs hand-written
code either way. An internal spec arrives when the internal API diverges from the public
one, which is expected in phase 8 when the gateway starts passing an authenticated user.

### Handlers

Each public route gets an explicit Go handler that validates, calls core and maps the
result. Most of them are thin, and a generic validating proxy could cover the CRUD routes
with less code. The handlers win because validation and error mapping need a home per
route, and writing Go is part of what this project is for.

### Ownership

| Concern | Gateway | Core |
|---|---|---|
| Public contract `api/openapi.yaml` | owns | — |
| Request validation | validates against the public contract, returns 422 problems | keeps its Pydantic validation as a second line |
| SSE framing | owns | — |
| OpenAI-compatible `/v1/chat/completions` (ADR 0006) | owns, built on the internal chat route | — |
| Auth, rate limits (phase 8) | owns | trusts its callers |
| Request id | accepts or mints one, forwards it as `X-Request-Id` | binds the forwarded id to its logs, as its middleware already does |
| `/healthz`, `/metrics` | its own | its own |
| Business logic, Postgres | — | owns |

### Errors

| Core outcome | Gateway returns |
|---|---|
| 404 problem | 404, passed through |
| any other 4xx | 502, logged as a gateway defect, because validated input should never draw a 4xx from core |
| 5xx | 502 |
| connection refused | 502 |
| timeout | 504 |

### Streaming

- Core keeps pulling the first fragment before it commits to a status, so a missing
  conversation is still a 404. The gateway reads core's status before writing any SSE.
- If core's stream breaks after the gateway has sent its headers, the gateway sends an
  `error` event and closes. A status code is no longer possible at that point.
- When the client disconnects, the gateway cancels its request to core by passing the
  incoming request's context to the outbound call. Core's `finally` then closes the
  stream and generation stops. Without this, a closed tab keeps the GPU busy.

### Reachability

Only the gateway may reach core. In development core binds `127.0.0.1`. Once services are
containerised, core and the gateway share a network that nothing else joins; the Rust
worker and SearXNG stay off it. A gateway that can be bypassed is the security theatre
ADR 0001 warns about.

Containerising the services and isolating them on a network is its own piece of work and
is outside phase 2 as this ADR scopes it. Where it lands is a PLAN.md decision.

### Order of work

1. The gateway reverse-proxies everything to core's current API, so it sits in front
   before any route is ported.
2. Core gains the NDJSON form of the messages route.
3. The gateway takes over public routes one at a time. Chat comes last because it carries
   the translation.
4. The public contract suite runs against the live gateway with core behind it.
5. The public-facing parts of `llm_stack_api` are deleted: SSE framing and anything only
   the public contract needed. The package keeps its name; its docstring says what it is.

## Consequences

- The spike still ends in phase 2. What survives is a transport. The enforcement rule in
  the repo instructions means new public endpoints go in the gateway; core keeps serving
  HTTP to the gateway alone, and gains an internal route only when a public one needs
  core logic.
- `test_contract.py` reaches the app through a single fixture, an `ASGITransport` in
  `conftest.py`. Pointing that fixture at a running gateway turns the suite into a
  black-box test of the whole path, which also catches drift between the Go client and
  core. CI's test job has to start both processes for it.
- The internal API is defined by its Python implementation plus that suite until it gets
  a spec. That is fine while it mirrors the public API and stops being fine when it
  diverges.
- Every request gains a hop over loopback, which is negligible next to model latency.
- The gateway's `/healthz` stays liveness only and never checks core, so a core outage
  doesn't get the gateway restarted too. Readiness (`/readyz`) comes later.
- Core trusting its callers holds only while the reachability rule holds. Phase 8 has to
  keep it true.

## Alternatives considered

**gRPC between gateway and core.** Typed, generated on both sides, and server streaming
fits chat well. ADR 0006 already chose OpenAPI/JSON as sufficient at this scale, and gRPC
here would add protobuf and code generation in two languages to a phase meant to be a
small port. Revisit if internal call volume makes JSON serialisation measurable.

**A separate internal spec with a generated Go client.** The first draft of this ADR.
Rejected for now because the spec would copy the public one by hand and the generator
would produce two functions. Becomes right when the internal API diverges.

**Gateway reads Postgres directly for conversations, calls core only for chat.** Saves an
internal route per CRUD endpoint. Rejected because the rules for a conversation live in
`ConversationStore`, so Go would reimplement them and two implementations of the same
rules would have to agree.

**Gateway as a permanent reverse proxy, core keeps the public API.** Step 1 above, kept
forever. Rejected because Go would add a hop and own nothing while the public API kept
growing in Python, which is the outcome ADR 0001 exists to prevent.

**A generic validating proxy for the CRUD routes.** Less code than per-route handlers.
Rejected for the reasons under Handlers.

**Core streams SSE, gateway passes it through.** No translation code. Rejected because
core would still own the public wire format, so the port would amount to a proxy. NDJSON
is also the simpler format to read in Go, one line per event.
