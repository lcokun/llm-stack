# llm-stack

A self-hosted LLM service with chat, document retrieval and web search, built to run on
one box with production-grade operations.

> **v2 is in active design. There is nothing to install yet.**
>
> v1 was a 400-line aiohttp proxy that impersonated the Ollama API. It worked, but its
> architecture had no way to carry documents, jobs, citations or users, so it is being
> replaced instead of patched.
>
> - [PLAN.md](PLAN.md) for the target architecture, phases and constraints
> - [docs/decisions/](docs/decisions/) for why the architecture is shaped this way
> - [docs/concepts/](docs/concepts/) for notes on the ideas behind it

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
```

Two processes and one database. Go at the edge, Python for orchestration, Rust for the
ingest worker and the desktop shell. Postgres is the single source of truth: vectors, job
queue and application data all live there. That choice is argued in
[ADR 0002](docs/decisions/0002-postgres-pgvector-not-qdrant.md) and
[ADR 0005](docs/decisions/0005-postgres-as-the-queue.md).

## Planned features

- chat with streaming responses, over an API of its own plus an OpenAI-compatible endpoint
- document ingest for PDF, DOCX, XLSX, PPTX, CSV, text, and images via OCR, run as
  background jobs with progress
- retrieval with hybrid search, reranking and citations that resolve to source and page
- web search through a self-hosted SearXNG, with result pages fetched and cleaned
- native multimodal vision, with a tool-based fallback for text-only models
- auth, per-user rate limits and model routing
- tracing, metrics, dashboards, alerting, tested backups and runbooks

## Running v1

v1 is preserved at the `v1-legacy` tag. It is unmaintained, has no authentication, and
binds every service to `0.0.0.0` with host networking. Do not expose it.

```bash
git worktree add ../llm-stack-v1 v1-legacy
cd ../llm-stack-v1
```

Its own README there documents the original setup.

## Status

Design complete, implementation not started. See [PLAN.md](PLAN.md) for the current phase.

## Licence

MIT. See [LICENSE](LICENSE).
