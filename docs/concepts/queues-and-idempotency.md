# Queues and idempotency

**Short version:** a queue splits the asking from the doing. Exactly-once delivery does
not exist, so every job must be safe to run twice.

## What a queue is for

v1 did this: `curl` a PDF up, and the HTTP request stayed open while the file was parsed,
chunked, and embedded one chunk at a time. For a 300-page PDF, minutes. During which:

- the client hangs with no idea whether it is working or wedged
- a dropped connection loses all the work and leaves the collection half-populated
- the synchronous parsing blocks the async event loop, so every chat request freezes

With a queue, the upload endpoint saves the file, writes a job row, and returns
`202 Accepted {"job_id": "..."}` in a few milliseconds. A separate worker process picks
the job up and grinds through it, updating the row. The client polls `GET /jobs/{id}`.

What that buys: the API stays responsive, a crash loses nothing because the job is still
queued, failures retry automatically, and more throughput means starting a second worker.

## The whole queue, in SQL

```sql
create table jobs (
  id           bigserial primary key,
  kind         text        not null,
  payload      jsonb       not null,
  state        text        not null default 'queued',  -- queued|running|done|failed
  attempts     int         not null default 0,
  max_attempts int         not null default 5,
  run_after    timestamptz not null default now(),
  locked_at    timestamptz,
  locked_by    text,
  last_error   text
);
create index on jobs (run_after) where state = 'queued';
```

Claiming one job:

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

## `SKIP LOCKED` is the load-bearing clause

`FOR UPDATE` takes a row lock. Without `SKIP LOCKED`, two workers racing for the same row
would block: worker B waits for worker A's transaction, then discovers the row is already
claimed and retries. The queue serialises, and workers spend their time queueing to look
at the queue.

`SKIP LOCKED` says that if a row is locked, pretend you cannot see it and take the next
one. Workers glide past each other and never contend. That one clause is what separates a
concurrent queue from a bottleneck.

## What the table gives you

The row lock guarantees an atomic claim, so no two workers get the same job.

Crash recovery works through what other systems call the visibility timeout. A worker that
dies mid-job leaves the row in `running` with a stale `locked_at`, and a reaper resets
rows locked longer than some interval:

```sql
update jobs set state = 'queued', locked_at = null, locked_by = null
where state = 'running' and locked_at < now() - interval '15 minutes';
```

Every queue system has this concept. Here it is a timestamp you can look at.

Retry with backoff is `attempts + 1` and `run_after = now() + backoff`. Dead-lettering is
setting `failed` once `attempts >= max_attempts`, and the row then *stays*, with its
payload and its error, for you to inspect.

Observability comes free: `select state, count(*) from jobs group by state` is queue depth
in the language you already use. With a broker, that is a separate tool.

## Exactly-once delivery does not exist

Not in Postgres, not in NATS, not in Kafka. Anything claiming it is either lying or
quietly describing at-least-once plus deduplication.

The reason is simple and unfixable: a worker can finish the work and then die before
recording that it finished. There is no code that runs after the process is gone. So the
job's lock expires and it runs again.

What you actually build:

> at-least-once delivery + idempotent handlers = effectively-once

## Idempotency, concretely

A handler is idempotent if running it twice leaves the same result as running it once.
Treat it as a design requirement for every handler you write.

The ingest transaction from
[ADR 0002](../decisions/0002-postgres-pgvector-not-qdrant.md) is idempotent:

```sql
BEGIN;
  DELETE FROM chunks WHERE document_id = $1;
  INSERT INTO chunks (document_id, ordinal, text, embedding) ...;
COMMIT;
```

Run it ten times, get the same chunks. The `DELETE` makes the operation a *replace*
instead of an *append*.

The obvious version is not idempotent:

```sql
INSERT INTO chunks (document_id, ordinal, text, embedding) ...;
```

Run it twice and the corpus silently doubles. Retrieval gets worse and nothing errors.
This is the bug class that makes people distrust their own RAG pipeline.

Other ways to get idempotency when a replace isn't natural:

- a unique constraint on something stable, such as `(document_id, ordinal)`, so a
  duplicate insert fails loudly instead of duplicating
- an idempotency key supplied by the caller, recorded on completion and checked first
- content hashing: v2 uses `sha256` on `documents`, so re-uploading identical bytes is a
  detected no-op rather than a second copy

## Push without a broker

Polling has a latency floor. Postgres `LISTEN`/`NOTIFY` fixes it: the enqueuer fires a
notification inside the transaction, and idle workers wake immediately.

Keep polling as a fallback anyway. A missed notification, from a worker restarting or a
dropped connection, would otherwise leave a job sitting forever. The fallback is what
makes the queue correct, and `NOTIFY` is what makes it fast.

## Why this project hand-rolls it

Covered in [ADR 0005](../decisions/0005-postgres-as-the-queue.md). The short reason is
that the Rust worker must speak the same queue. A Python library's table layout would have
to be reverse-engineered and reimplemented in `sqlx`, and any mismatch is a data race
found at 2am. Thirty lines of documented SQL is a *protocol*, and porting a protocol is
easy.

The longer reason is pedagogical. At-least-once, visibility timeouts, ack/nak, backoff,
dead-letter and backpressure are identical concepts in every queue system. Implement them
once in SQL and JetStream's configuration later reads as a description of something you
have already built.
