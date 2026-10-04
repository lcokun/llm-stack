# llm-stack v2 — plan

A self-hosted LLM service, rebuilt from scratch. v1 was a 400-line aiohttp proxy that
impersonated Ollama; v2 is a real service with a database, a job queue, an API of its
own, and production-grade operations.

**The goal is learning rather than shipping features.** Specifically: backend and API
design, DevOps/SRE practice, AI/LLM engineering with honest evals, and Go and Rust on a
real system rather than in tutorials. Target is *ops-complete single box*: stays
self-hosted, but with everything a production service has, including CI/CD, monitoring,
alerting, backups with tested restores, zero-downtime deploys, runbooks and SLOs.

Progress will be slower than a Python-only build. That is the accepted price, recorded
in [ADR 0001](docs/decisions/0001-two-processes-not-three-services.md).

## Target architecture

```
Tauri shell (Rust) ─┐
browser / PWA ──────┼──▶  gateway (Go)  ──▶  core (Python)  ──▶  Ollama
any OpenAI client ──┘     auth, rate limit,   tool calling,       SearXNG
                          SSE, static files,  RAG, prompts,
                          audit, metrics      model registry
                                 │                   │
                                 └──▶  jobs  ──▶  worker (Rust)
                                                 parse → chunk → embed → upsert
                                                        │
                                      Postgres + pgvector
                                      documents · chunks · jobs · conversations · users
```

Two processes and one database, not three services. The gateway boundary is drawn in
code from the first commit and extracted to Go in phase 2, while the port is small.

## Verified facts

Checked 2026-10-03, extended 2026-10-05. Anything not listed here is training-era
knowledge and unverified.

| Fact | Status |
|---|---|
| `pgvector` **0.8.7** (2026-10-01), supports PostgreSQL 13–18 | primary source |
| **CVE-2026-3172**, a buffer overflow in parallel HNSW builds, fixed in 0.8.2, so `>= 0.8.2` is a security floor | primary source |
| **Tauri 2.11.5**, WebKitGTK 4.1 on Linux | primary source |
| `qwen3:4b` 2.5 GB, tools and thinking, no vision; `nomic-embed-text` 274 MB at 768 dimensions; Ollama returns NDJSON from `/api/chat` and declares capabilities from `/api/show` | primary source, 2026-10-05 |
| Candidate models: Qwen3-VL-8B ~6 GB @ Q4 (strong at document reading); Qwen3.5-9B Q4_K_M 6.6 GB, Apache 2.0, native vision + tools; Gemma 4 native vision at all sizes | **secondary sources, verify against ollama.com before pulling** |

### Local toolchain

| Tool | State |
|---|---|
| docker 29.7.2 + compose 5.5.1 | installed |
| rustc / cargo 1.98.1 | installed |
| uv 0.9.3 | installed |
| node 26.8.1 / npm 12.0.2 | installed |
| psql 18.6 (client) | installed |
| go 1.27.0 | installed |
| just 1.58.0 | installed |
| GPU | RTX 4070 Laptop, **8188 MiB** |

System Python is 3.14.7. **Pin the project to 3.12 or 3.13 via `uv`.** The
document-parsing stack (`pymupdf`, `python-docx`, `openpyxl`, `python-pptx`) historically
lags new CPython minors on prebuilt wheels.

## Phases

Ordered so Go lands in month one and Rust in month two, so neither sits behind a phase
that might never arrive, and so every phase ends with something deployed and running.

### Phase 0 — foundations · **complete 2026-10-03**
- [x] install Go and `just`
- [x] `justfile` with `lint`, `fmt`, `test`; `dev` and `migrate` arrive with the
      services they run
- [x] repo layout per [ADR 0008](docs/decisions/0008-monorepo-layout.md); directories
      appear in git as they gain files
- [x] `api/openapi.yaml`, the contract, written before implementations, scoped to
      the phase 1 surface only
- [x] `FakeClient` behind the `InferenceClient` seam, with its contract tests
- [x] CI running `lint` and `test` on every PR, both required checks
- [x] branch protection on `main` *(Mel, GitHub settings)*
- [x] `.gitignore` rewrite, README accuracy pass, delete `vision-bridge/`,
      `Modelfile.tools` and `docker-compose.yml`; `searxng/` moved to `deploy/`

**Deferred out of phase 0, on purpose.** CI path filters: a path-filtered job that is
also a required status check never reports on PRs that miss those paths, which leaves
them permanently unmergeable. They arrive with the aggregate job once Go or Rust make CI
slow enough to pay for it. A type checker in CI was the other known gap; Pyright
joined `just lint` during phase 1, so CI runs it on every PR.

### Phase 1 — thin vertical slice · Python · **complete 2026-10-05**
- [x] Postgres in compose, pinned; `db/migrations/` with a standalone migration step
      via dbmate
- [x] schema: `documents`, `chunks`, `jobs`, `conversations`, `messages`
- [x] chat end-to-end: own API → `core` → `FakeClient` → streamed response as SSE
- [x] `api/` ÷ `core/` boundary, `core/` HTTP-free, enforced by a test that parses
      every core module for forbidden imports
- [x] structured logging with request-id correlation, and `/metrics`
- [x] one end-to-end test in CI, against a pgvector service container with migrations
      applied as their own step
- [x] swap `FakeClient` for Ollama and confirm parity, via one contract suite
      parametrised over both backends

Responses are validated against `api/openapi.yaml` in the test suite, so hand-written
models cannot drift from the contract without failing CI.

### Phase 2 — extract the gateway · **Go**
- [ ] port `api/` to Go while it is ~200 lines
- [ ] NDJSON → SSE translation at the edge
- [ ] generate the Go client from `api/openapi.yaml`
- [ ] `core` moved onto a bridge network, no published port
- [ ] Python API layer deleted, the spike ends here

### Phase 3 — web UI spike · JS
- [ ] vanilla JS, no framework, deliberately plain
- [ ] chat with SSE streaming
- [ ] file upload, document list and delete
- [ ] model picker showing registry capabilities

### Phase 4 — minimal ingest worker · **Rust**
- [ ] jobs table claimed with `FOR UPDATE SKIP LOCKED`, behind a `JobQueue` interface
- [ ] `202 Accepted` + `GET /jobs/{id}`
- [ ] Rust worker: one file type, one job at a time, synchronous
- [ ] idempotent ingest, `DELETE` then `INSERT` by `document_id`
- [ ] reaper for stale `locked_at`

### Phase 5a — ingest quality · **Rust**
- [ ] structure-aware chunking instead of word counts
- [ ] nomic `search_document:` / `search_query:` prefixes
- [ ] page and offset metadata for citations
- [ ] `data_only=True` equivalent for spreadsheets
- [ ] per-page fallback for PDFs with no text layer

### Phase 5b — evals, then query-side retrieval · Python
- [ ] eval set: 20+ Q/A pairs including a scanned page, a screenshot with code, a chart,
      and a photo
- [ ] harness reporting recall@k and nDCG; re-measure phase 5a retroactively
- [ ] hybrid search: vector + Postgres FTS, fused with RRF
- [ ] reranking over the top ~20
- [ ] query rewriting
- [ ] benchmark native multimodal vs abliterated-plus-tool, and decide the default model

### Phase 6 — tool calling, search, citations
- [ ] model registry with declared capabilities; replace prefix routing with tool calling
- [ ] `inspect_image` tool as the vision fallback for text-only models
- [ ] SearXNG secret to `.env` and rotated; search result pages fetched and cleaned
- [ ] citations end-to-end, resolving to chunk and page
- [ ] images in ingest: OCR **and** VLM description
- [ ] **web UI graduates**: framework decision, renders citations and tool calls

### Phase 7 — worker grows up · **Rust**
- [ ] async and concurrent
- [ ] batched embedding calls
- [ ] retries with backoff, dead-letter, backpressure
- [ ] benchmark against the Python baseline, so Rust's value is measured not assumed

### Phase 8 — ops-complete
- [ ] auth: API keys and browser sessions; per-user rate limits
- [ ] Caddy + TLS; nothing exposed beyond Tailscale
- [ ] OpenTelemetry tracing across all three services
- [ ] Prometheus + Grafana; latency, tokens, queue depth, error rate
- [ ] alerting on SLO burn
- [ ] backups **and a tested restore drill**
- [ ] staging environment; zero-downtime deploy
- [ ] load test; deliberate failure drills
- [ ] runbooks in `docs/runbooks/`

### Phase 9 — optional
- [ ] Tauri shell: packaging, cross-platform CI, signing, auto-update
- [ ] `pg_search` if evals show lexical ranking is the limiter
- [ ] vLLM, if the workstation's 32 GB card returns from rent

## Constraints

- **8188 MiB** of VRAM. One multimodal model plus embeddings is the ceiling. See
  [docs/concepts/vram-budget.md](docs/concepts/vram-budget.md). Develop against
  `FakeClient`.
- Single operator. No public exposure beyond Tailscale.
- Public repo, pinned on the GitHub profile. It doubles as a portfolio piece, so the
  README must never describe software that does not exist.
- Git is Mel's. Claude prints command lines and never executes them. See
  [docs/concepts/git-workflow.md](docs/concepts/git-workflow.md).

## Decisions

| ADR | Decision |
|---|---|
| [0001](docs/decisions/0001-two-processes-not-three-services.md) | Two processes, not three services; Go extracted in phase 2 |
| [0002](docs/decisions/0002-postgres-pgvector-not-qdrant.md) | Postgres + pgvector; Qdrant and Tantivy cut |
| [0003](docs/decisions/0003-native-multimodal-not-vision-chain.md) | Native multimodal; vision chain dies; model registry |
| [0004](docs/decisions/0004-ollama-behind-an-inference-interface.md) | Ollama behind `InferenceClient`; vLLM deferred |
| [0005](docs/decisions/0005-postgres-as-the-queue.md) | Hand-rolled Postgres job queue |
| [0006](docs/decisions/0006-own-api-plus-openai-compat.md) | Own API + OpenAI-compatible endpoint |
| [0007](docs/decisions/0007-web-frontend-tauri-shell.md) | One web frontend, Tauri shell later |
| [0008](docs/decisions/0008-monorepo-layout.md) | Same repo, polyglot monorepo, repo-owned migrations |

## Open questions

| Question | Resolved in |
|---|---|
| Frontend framework: Svelte or React, or stay vanilla | phase 6 |
| OCR engine: Tesseract or VLM-based | phase 6 |
| Default chat model | phase 5b, by eval numbers |
| Full v2 README | when there is a running system to document |
| CI path filters + aggregate job | phase 2, when Go makes CI slow |
| `ChatEvent` unreferenced, so generators may skip it | phase 2, via the generator's emit-all flag |

## Concepts

Learning notes written as each idea landed:

- [queues-and-idempotency.md](docs/concepts/queues-and-idempotency.md)
- [dual-write-problem.md](docs/concepts/dual-write-problem.md)
- [vram-budget.md](docs/concepts/vram-budget.md)
- [streaming-ndjson-sse-websockets.md](docs/concepts/streaming-ndjson-sse-websockets.md)
- [git-workflow.md](docs/concepts/git-workflow.md)
- [ids-and-ordering.md](docs/concepts/ids-and-ordering.md)
- [observability.md](docs/concepts/observability.md)
- [inference-seam.md](docs/concepts/inference-seam.md)
