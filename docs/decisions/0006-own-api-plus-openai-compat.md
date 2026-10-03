# 0006 — Own API plus an OpenAI-compatible endpoint

- **Status:** accepted
- **Date:** 2026-10-03

## Context

v1's entire shape was dictated by its client. `oterm` speaks the Ollama API, so
`bridge.py` impersonated an Ollama server: `handle_tags` faked a model list,
`passthrough` forwarded anything unrecognised, responses were NDJSON, and the whole
enrichment mechanism worked by rewriting `last_user["content"]`, because that is the only
field in Ollama's schema where extra context can be hidden.

That was a reasonable trade for a weekend proxy. It is fatal for v2, because the Ollama
API has no vocabulary for anything being added: no conversations, no documents, no jobs,
no citations, no users, no tool-call transcripts, no model capabilities. Every feature in
ADRs 0002, 0003 and 0005 is inexpressible in the protocol the client speaks.

The choice was therefore: keep the Ollama API and be unable to expose the product, or
design an API and lose the off-the-shelf client.

## Decision

Two surfaces.

The project's own API carries the product: conversations, messages, documents, jobs,
citations, models and capabilities, usage. Designed for the features rather than
retrofitted into someone else's schema. The OpenAPI spec lives at `api/` in the repo
root, outside any service, because the gateway, core and frontend all consume it. See
[0008](0008-monorepo-layout.md).

Alongside it, an OpenAI-compatible `/v1/chat/completions` for compatibility.

Ollama mimicry dies, and `oterm` goes with it.

## Consequences

**OpenAI-shaped rather than Ollama-shaped, and the reason is ecosystem.** It is the de
facto standard, so one endpoint buys every OpenAI-compatible chat frontend and every
client SDK, permanently. Ollama compatibility buys `oterm`. The compat endpoint is
deliberately not the design driver: it exposes the subset of functionality that fits its
schema, and the rich surface carries the rest.

**The client question becomes real**, since `oterm` is no longer an option. Resolved in
[0007](0007-web-frontend-tauri-shell.md).

**Streaming format changes.** v1 streamed Ollama's NDJSON. Browsers want SSE
(`text/event-stream`). The NDJSON to SSE translation is a concrete job for the gateway.
See
[concepts/streaming-ndjson-sse-websockets.md](../concepts/streaming-ndjson-sse-websockets.md).

**Contract-first becomes possible and mandatory.** With a spec at `api/`, the Go client
and TypeScript types can be generated from it, so three sides cannot silently disagree.
This is also what makes the phase 2 Go extraction mechanical, since the contract already
exists and does not change when the implementation language does.

**Accepted cost:** designing an API is real work and the first version will be wrong in
places. Mitigated by versioning the spec and by the frontend being its first consumer.
Nothing exposes a badly designed API faster than having to consume it.

**v1 bugs that disappear with the mimicry:** only `/api/chat` was enriched, so
`/api/generate` and `/v1/*` silently bypassed vision, search and RAG entirely; and
`/api/tags` allowlisted two models, hiding everything else on the server.

## Alternatives considered

**Keep the Ollama API only.** Rejected. It cannot express documents, jobs, citations,
conversations or users. Keeping it means either never exposing those features or
continuing to smuggle them through `content` string rewriting, which is how v1 ended up
with prefix routing and one feature per message.

**OpenAI-compatible only, no bespoke API.** Rejected. It has no vocabulary for document
management, ingest job status, or citation provenance either. Better than Ollama's, still
not sufficient.

**Keep an Ollama-compatible surface alongside, to retain `oterm`.** Rejected. It is a
third surface to maintain for one client, and that client cannot display the features
that justify the rewrite. If an Ollama-speaking client is ever wanted, the compat
endpoint can be added later, but it should not constrain the design now.

**gRPC or protobuf for the internal contract.** Not adopted. OpenAPI/JSON is sufficient
at this scale, is directly consumable by a browser without a proxy layer, and keeps the
compat endpoint trivial. Revisit only if internal call volume makes serialisation
measurable.
