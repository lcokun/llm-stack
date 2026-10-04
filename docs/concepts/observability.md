# Observability

**Short version:** a log line is for a human reading one request; a metric is for a
machine watching all of them. Logs answer "what happened to *this* request", metrics
answer "is the service healthy" — and the two failure modes are an unparseable log and a
metric label with unbounded cardinality.

## Structured logging

Prose logs are write-only. `Started request to /conversations/0199abc...` can be read but
not queried: no filter for "every 5xx in the last hour", no grouping by route. One JSON
object per line makes the stream a dataset:

```json
{"ts": "2026-10-04T16:21:49+00:00", "level": "INFO", "logger": "llm_stack_api.middleware",
 "msg": "request", "request_id": "hello-123", "method": "GET", "route": "/healthz",
 "path": "/healthz", "status": 200, "duration_ms": 0.77}
```

`jq 'select(.status >= 500)'` today, a log aggregator in phase 8, and nothing in between
has to change.

Two constraints follow from "one object per line". A traceback is multi-line, so it goes
in a string field (`stack`) where `json.dumps` escapes the newlines — put it in `msg` and
every downstream parser breaks. And a value that will not serialise must not raise:
`default=str` on the dump means a `UUID` in an `extra=` dict degrades to its string form
instead of throwing *inside the logging call*, which is the worst place to throw.

## The correlation id, and why it is a ContextVar

One request produces log lines from the HTTP layer, from `core`, and from whatever
`core` calls. They are only useful together, which needs a shared id on every line.

Passing `request_id: str` down through every signature would put an HTTP concern in
`core`'s API — exactly what [ADR 0001](../decisions/0001-two-processes-not-three-services.md)
forbids. A `contextvars.ContextVar` is scoped to the current async task rather than the
process, so concurrent requests each see their own value:

```python
request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
```

`RequestContext` sets it, `JsonFormatter` reads it, and nothing between them knows it
exists. `core` logs normally and the id appears anyway.

The id comes from the client's `X-Request-ID` when sent and is generated when not, then
echoed back on the response — so a user reporting a bug can quote the id that appears in
the logs.

## Cardinality is the metric failure mode

Prometheus stores one time series per distinct combination of label values. A label
containing a UUID therefore mints a new series per request, each one retained forever.
That is a memory leak in the monitoring system, and the standard way people take down
their own Prometheus.

So the HTTP metrics label with the matched *route template*, never the path:

```python
def _route(scope: Scope) -> str:
    return getattr(scope.get("route"), "path", UNMATCHED_ROUTE)
```

`/conversations/{id}` — one series for every conversation. Starlette sets `scope["route"]`
before handing off to the endpoint, so middleware can read it once the inner app returns.
Unmatched paths collapse into a single `unmatched` series rather than one per scanner
probe, which matters the moment the service is reachable by anything but you.

The test that protects this asserts a *negative* — that the conversation id does **not**
appear in `/metrics`. The positive assertion alone still passes after someone "fixes" the
label to use the raw path.

## Counters, histograms, and buckets

A counter only goes up; the rate is computed at query time. A histogram counts
observations into fixed buckets so quantiles can be estimated.

| Metric | Type | Survives phase 2? |
|---|---|---|
| `http_requests_total` | counter | no — the Go gateway owns it |
| `http_request_duration_seconds` | histogram | no — same |
| `inference_requests_total` | counter | yes |
| `inference_time_to_first_fragment_seconds` | histogram | yes |
| `inference_stream_duration_seconds` | histogram | yes |

Buckets are chosen up front and cannot be changed retroactively — historical
observations are already counted. The library default tops out near 10s, which is fine
for HTTP and useless for a model stream, hence a shared ladder out to 60s.

On a streaming endpoint, total duration is dominated by how long the answer is, so it is
not a latency signal. Time-to-first-fragment is the number a user experiences as "is this
thing broken". Collapsing the two answers neither question, which is why
`ChatService.send` records both.

`inference_requests_total` separates `cancelled` from `error`, because a closed browser
tab raises `GeneratorExit` at the `yield` and would otherwise look like a backend failure
— paging you for users navigating away.

## The bug: reachability as an on switch

With `--no-access-log` passed, every request still logged twice. uvicorn does not consult
the flag per request:

```python
self.access_log = self.access_logger.hasHandlers()   # httptools_impl.py
```

The flag works by making `uvicorn.access` unreachable — clearing its handlers and setting
`propagate = False`. Then `configure_logging` ran later, at lifespan startup, setting
`propagate = True` on every uvicorn logger to route them through the JSON formatter. That
re-exposed root's handler, `hasHandlers()` went back to `True`, and uvicorn resumed access
logging — in JSON, which made it look deliberate.

The fix is to leave that one logger unreachable, since `RequestContext` is the access log.
Raising its level would not have worked: `hasHandlers()` ignores levels.

> Logging configuration is global mutable state, and libraries read it at times you do
> not choose.

Anything that sets `propagate` or assigns `handlers` is reaching into a process-wide
structure that other code already configured. The `_installed` handler reference in
`configure_logging` exists for the same reason: replacing `root.handlers` wholesale would
silently rip out pytest's `caplog` handler and break every log assertion in the suite.

## What this does not give us

**Not tracing.** Logs and metrics describe one process. "Which of the three services made
this slow" needs spans with a propagated trace id — phase 8, OpenTelemetry. The
`X-Request-ID` header is the seed of that: it is already propagated, so it becomes a
trace id rather than being replaced by one.

**Not aggregated.** Metrics live in a per-process registry and vanish on restart; nothing
scrapes `/metrics` yet and nothing ships the logs anywhere. More than one uvicorn worker
would report one worker's numbers at random, which `PROMETHEUS_MULTIPROC_DIR` fixes when
it becomes true.

**Not access-controlled.** `/metrics` is on the public port and names models and routes.
Phase 8 authenticates it or moves it to an admin port.

**Not alerting.** A metric nobody looks at is a metric that does not exist. The SLOs and
burn-rate alerts that make these numbers load-bearing are phase 8.
