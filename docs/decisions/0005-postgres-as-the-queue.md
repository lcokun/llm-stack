# 0005 — Postgres as the job queue, hand-rolled

- **Status:** accepted
- **Date:** 2026-10-03

## Context

v1 had no queue. `handle_upload` accepted a multipart file and parsed, chunked and
embedded it inside the HTTP request, one chunk at a time. For a 300-page PDF that is
minutes during which the `curl` hangs with no progress signal, a dropped connection
loses all work and leaves the collection half-populated, and the synchronous parsing
blocks the async event loop so every chat request freezes.

A queue splits the asking from the doing: the upload endpoint saves the file, writes a
job row, returns `202 Accepted {"job_id": ...}` in milliseconds, and a separate worker
process does the slow work while the client polls.

The question was which queue. The v2 design proposed Redis or NATS.

## Decision

A hand-rolled Postgres queue, behind a `JobQueue` interface.

```sql
create table jobs (
  id           bigserial primary key,
  kind         text        not null,
  payload      jsonb       not null,
  state        text        not null default 'queued',
  attempts     int         not null default 0,
  max_attempts int         not null default 5,
  run_after    timestamptz not null default now(),
  locked_at    timestamptz,
  locked_by    text,
  last_error   text
);
create index on jobs (run_after) where state = 'queued';
```

```sql
update jobs set
  state = 'running', locked_at = now(), locked_by = $1, attempts = attempts + 1
where id = (
  select id from jobs
  where state = 'queued' and run_after <= now()
  order by run_after
  for update skip locked
  limit 1
)
returning *;
```

`SKIP LOCKED` is the load-bearing clause. `FOR UPDATE` takes a row lock; without
`SKIP LOCKED` two workers racing for the same row would *block*, serialising the queue.
`SKIP LOCKED` makes a locked row invisible so workers glide past each other and never
contend.

Use `LISTEN`/`NOTIFY` for wakeup, with polling as the fallback that catches anything a
missed notification dropped. The fallback is what makes it correct.

## Consequences

**Transactional enqueue, the decisive consequence.** The document and the job that
processes it are created in one transaction:

```sql
BEGIN;
  INSERT INTO documents (...) RETURNING id;
  INSERT INTO jobs (kind, payload) VALUES ('ingest', '{"document_id": ...}');
COMMIT;
```

With an external broker this is the dual-write problem from
[0002](0002-postgres-pgvector-not-qdrant.md) again: commit then publish, and a failed
publish leaves a document nobody will ingest; publish then commit, and a failed commit
leaves a job referencing nothing. The standard remedy is the outbox pattern, writing the
message to a Postgres table inside the transaction and having a relay forward it. Which
means the correct way to use a broker alongside a database is to build a Postgres queue
first, then add a broker behind it. The broker is strictly additive, and adding it never
removes the need for the queue.

**What the table gives for free:** atomic claim; crash recovery, where a dead worker
leaves a stale `locked_at` and a reaper resets rows locked longer than some interval,
which is a visibility timeout made visible in a table; retry with backoff; and a
dead-letter state where `attempts >= max_attempts` keeps the row *with its payload and
error* for inspection.

**Observability and backups for free.** `select state, count(*) from jobs group by state`
is queue depth in the language already used for everything else. A failed job's payload
is a `SELECT` away. `pg_dump` captures queue state, so there is one backup procedure and
one restore drill. With a broker, queue depth, failed-message inspection and backup are
three separate tools to learn and monitor.

**Hand-rolled rather than a library, for a specific reason.** The Rust worker must speak
the same queue. A Python library's table layout and locking conventions would have to be
reverse-engineered and reimplemented in `sqlx`, and any mismatch is a data race found at
2am. Thirty lines of documented SQL is a protocol, and porting a protocol is
straightforward. This is a case where the dependency costs more than the code it saves.

**Accepted weaknesses:** fan-out to several independent consumer groups is awkward (NATS
is built for it; this stack has one consumer type); there is no replay-from-offset; and
`done` rows accumulate, needing periodic cleanup or partitioning.

**Idempotency becomes a design requirement.** Exactly-once delivery does not exist, since
a worker can finish the work and die before recording that it did, so the job runs again.
What you build is at-least-once delivery plus idempotent handlers. The ingest transaction
from [0002](0002-postgres-pgvector-not-qdrant.md) is idempotent by construction:
`DELETE FROM chunks WHERE document_id = $1` then `INSERT` gives an identical result run
twice, where a naive append would silently double the corpus. See
[concepts/queues-and-idempotency.md](../concepts/queues-and-idempotency.md).

## Alternatives considered

**NATS JetStream.** True pub/sub fan-out, replay, much higher throughput, ack/nak/term
semantics built in, single binary. Lost on the dual-write objection and on being a
second stateful system to operate. The honest counter is that JetStream would teach more,
and the answer is that the transferable things are the *concepts*, which are identical:
at-least-once, visibility timeouts, ack/nak, backoff, dead-letter, idempotency,
backpressure. On Postgres you implement them and understand them; on JetStream you
configure them and know the knob names. Hand-roll first and JetStream's configuration
reads as a description of something already built. Revisit if multiple independent
consumer types appear, or on its own merits as a learning goal.

**Redis.** An in-memory key-value store used as a queue. Rejected: persistence is
optional and best-effort, so depending on config a crash loses recent writes, which means
Redis is not where truth lives. It also carries a licence question, from the 2024
relicensing and the Valkey fork (training-era, verify if ever adopted).

**"It won't scale."** Not accepted as an objection. A tuned Postgres queue handles
thousands of jobs per second against a workload of tens per day, roughly six orders of
magnitude of headroom.

## Note on seams

This is the third decision settled by the same move:

| ADR | Seam |
|---|---|
| [0001](0001-two-processes-not-three-services.md) | `api/` ÷ `core/`, so Go extraction is a port not a redesign |
| [0004](0004-ollama-behind-an-inference-interface.md) | `InferenceClient`, so trying vLLM is a weekend |
| 0005 | `JobQueue`, so adopting NATS is contained |

Put a seam where you expect to change your mind, and nowhere else. Seams cost
indirection and indirection costs clarity. There are three in the whole architecture,
each at a point where the decision was honestly uncertain. Do not add more; do not remove
these.
