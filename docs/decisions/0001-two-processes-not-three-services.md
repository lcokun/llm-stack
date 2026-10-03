# 0001 — Two processes, not three services

- **Status:** accepted
- **Date:** 2026-10-03

## Context

The v2 design started as three services: a Go gateway (auth, rate limiting, routing,
SSE, metrics), a Python orchestrator (tool calling, RAG, prompts), and a Rust ingest
worker. That shape needed justifying before anything was built on it.

A service is a separately running process reached over a network. It brings its own
deploy, its own crash domain, a network hop with new failure modes, its own config,
secrets, logs, metrics and health check, plus a contract with its callers that must be
versioned, because you cannot deploy both sides at the same instant.

The three proposed splits are not the same kind of claim.

The worker split is justified on technical grounds today. In the v1 bridge,
`handle_upload` parsed and embedded documents inside the async web server, so a large
PDF blocked the event loop and froze every chat request. Web processes must answer in
milliseconds; workers chew through long, failure-prone work. They want different
timeouts, concurrency, scaling and restart behaviour. The split is near-universal
(Sidekiq, Celery) and even aggressively monolithic applications make it.

The gateway split is not. Gateways exist to front *many* backend services with one
auth/TLS/rate-limit layer, to isolate a hardened edge, to meet edge performance needs
the app language can't, or to draw a team boundary. With one backend service every item
on that list collapses into middleware, roughly 150 lines inside the service that
already exists, versus a second deployable in a second language.

There is also a trap: a gateway you can bypass is security theatre. If the gateway
authenticates but the orchestrator is independently reachable, you have added a hop and
no security. v1 got this exactly wrong, with `network_mode: host` on all four services
and no auth anywhere, so a gateway layered on that arrangement would have secured
nothing.

Against all that, Mel's stated worry is real and was raised explicitly: that a Python
version would work well enough and Go and Rust would never actually happen.

## Decision

Build two processes in one codebase and one language to start: a FastAPI web process
and a Python worker process, with Postgres.

Draw the `api/` ÷ `core/` boundary in code from the first commit, exactly where the
gateway boundary will eventually fall. `core/` knows nothing about HTTP. These are an
honest separation of concerns rather than packages cosplaying as services.

Then extract `api/` into a Go gateway at roughly week three, while it is ~200 lines.
The extraction is the mitigation for the abandonment risk, and its timing is the point: a
200-line port is a weekend and needs no justification, while a 2000-line port is a month
that has to be argued for against features you actually want. After the extraction, Go is
a fact about the project rather than a plan, and new endpoints go there because that is
where endpoints live.

The Rust worker follows the same pattern: start minimal in month two (one file type, one
job at a time, no concurrency) and grow it, reimplementing logic already written and
understood rather than inventing it in an unfamiliar language.

## Consequences

- The gateway boundary exists in code before it exists in deployment, so extraction is
  mechanical rather than a redesign, and there is a working Python implementation to
  diff behaviour against and benchmark.
- Go lands in month one, Rust in month two. Neither sits behind a phase that may never
  arrive.
- Progress on features is slower than staying in Python throughout. By month three there
  will be noticeably fewer working features. That is the accepted price of the stated goal
  being learning rather than shipping.
- Distributed-systems learning is not lost. It lives in the queue, covering at-least-once
  delivery, idempotency, visibility timeouts, retries and backpressure, which teaches more
  than a second HTTP hop would. See [0005](0005-postgres-as-the-queue.md).
- The ops-complete goal is unaffected. Zero-downtime deploys, backups, restore drills,
  SLOs, alerting and tracing are as real with two processes as with five, and get done
  properly instead of three times badly.
- The repo-local instructions carry an enforcement duty: the Python API layer is a
  labelled spike, and requests to extend it after phase 2 get redirected to the Go
  gateway. Code named disposable on day one does not accumulate affection.

## Alternatives considered

**Three services from the start.** Rejected. For one user on one box, a single Python
service plus Postgres is architecturally sufficient; the gateway's only honest
justification was pedagogical. Starting there would have meant learning a new language
and a new discipline simultaneously, so every bug would have had two possible causes.
It also front-loads the invisible costs: no single-process debugging, "why was this
slow" requiring distributed tracing before it can be answered at all, deploys becoming
an ordering problem, and local dev needing N processes started in sequence.

**One process, no worker.** Rejected. It preserves the v1 bug where document parsing
blocks the event loop, and the web/worker split is the one that pays for itself
immediately.

**Modular monolith with extraction deferred to "later".** Rejected as originally
proposed. This ADR's first draft put the Go extraction at month five, which is precisely
the shape that never happens. Week three is the fix.

## Note on the principle

> The boundary matters more than the process.

A clean boundary in code, meaning a narrow interface, no reaching around it, and data
crossing as explicit types, makes the function-call-versus-HTTP-call question a deployment
detail. A bad boundary is not rescued by splitting into services; it becomes a
*distributed* mess, which is strictly harder to debug. Distributed systems do not grant
modularity, they punish its absence.
