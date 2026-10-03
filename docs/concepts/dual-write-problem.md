# The dual-write problem

**Short version:** two stores that must agree is a distributed transaction, and there is
no clean fix. Avoid needing one.

## The setup

You ingest a document. You need two things to happen:

1. a row in Postgres recording that the document exists
2. its vectors in the vector database

You cannot do both atomically, because they are different systems. So you do them in
some order, and either order has a failure mode:

| Order | What fails | Result |
|---|---|---|
| Postgres first | the vector write | a document the registry claims is indexed, with nothing in the index |
| Vector DB first | the Postgres commit | orphan vectors pointing at a document that does not exist |

Neither outcome is detectable from inside the other system. Nothing is "corrupt" in a way
a constraint would catch. The two stores simply disagree, silently, until a query
surprises you.

## Why "just retry" doesn't fix it

Retrying the second write helps with transient failures. It does nothing for the case
that matters, which is the process dying between the two writes. There is no code that
runs after the process is gone.

## The real remedies

The outbox pattern writes the *intent* to a table in the same database, inside the same
transaction as the data:

```sql
BEGIN;
  INSERT INTO documents (...);
  INSERT INTO outbox (kind, payload) VALUES ('index_document', '{...}');
COMMIT;
```

Now one atomic commit records both the fact and the work. A separate relay process reads
the outbox and writes to the other system, marking rows done. Failures are retried from
a durable record, and a crash loses nothing because the intent survived the commit.

Reconciliation periodically compares both stores and re-indexes the drift. It is a safety
net, so it bounds how long a disagreement lasts without preventing one.

## What the outbox pattern actually is

It is a job queue in Postgres: a table of pending work, polled by a worker, marked done
on success.

So the correct way to use a second store alongside your database is to build a Postgres
queue first, then put the second store behind it. The second store is strictly additive,
and adding it never removes the need for the queue.

## How this project avoids it

Twice, on purpose:

- [ADR 0002](../decisions/0002-postgres-pgvector-not-qdrant.md) puts vectors in Postgres
  as rows via `pgvector`, so document and vectors commit together. This is why Qdrant was
  cut, and the reason was consistency rather than performance.
- [ADR 0005](../decisions/0005-postgres-as-the-queue.md) makes the job queue a Postgres
  table, so a document and the job that processes it are created in one transaction. This
  is why NATS was deferred.

```sql
BEGIN;
  INSERT INTO documents (...) RETURNING id;
  DELETE FROM chunks WHERE document_id = $1;
  INSERT INTO chunks (document_id, text, embedding) ...;
  INSERT INTO jobs (kind, payload) VALUES ('ingest', '{"document_id": ...}');
COMMIT;
```

One transaction. Either all of it happened or none of it did, so there is no
disagreement left for anything to reconcile.

## The general rule

> Do not introduce a second source of truth for state that must agree with your database.

When you genuinely must, for a search engine or a cache or an external index, reach for
the outbox pattern deliberately, and know you are accepting an eventual-consistency
window and a reconciliation job as the price.

## Where this does *not* apply

Writing to a store whose contents are derived and disposable is not a dual write in the
dangerous sense. A cache that can be rebuilt from the database, or a search index you are
willing to reconstruct from scratch, can disagree temporarily without misleading anyone,
provided the database remains the single authority and the derived store is rebuildable.
The problem is specifically two stores that both claim to be authoritative.
