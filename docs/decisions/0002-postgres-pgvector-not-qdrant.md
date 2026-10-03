# 0002 — Postgres + pgvector, not a dedicated vector database

- **Status:** accepted
- **Date:** 2026-10-03

## Context

v1 used ChromaDB over HTTP, unpinned and unauthenticated. The v2 design initially
replaced it with Qdrant for native hybrid search, plus Tantivy for BM25 keyword ranking.

Retrieval needs five separable things:

1. semantic search: embed the query, find nearest vectors
2. lexical search, meaning BM25 keyword matching, which matters because embeddings are
   genuinely bad at rare terms such as names, error codes, acronyms, version numbers and
   negation
3. fusion, combining the two ranked lists, usually with Reciprocal Rank Fusion
4. metadata filtering, for "only this document" or "only ingested after September"
5. reranking, a cross-encoder over the top ~20

A dedicated vector DB provides 1, part of 3, and a limited 4. It does not provide 5 at
all, which is model work.

Scale matters here and the numbers are small. A 300-page PDF is roughly 150k words,
about 300 chunks at 500 words each. A hundred such documents is ~30,000 vectors.
Dedicated engines start meaningfully outperforming pgvector in the millions, three
orders of magnitude away.

## Decision

Use Postgres with the `pgvector` extension. Vectors are rows in the same database as
everything else. No Qdrant, no separate search service.

Pin `pgvector >= 0.8.2`. Verified 2026-10-03: current release is **0.8.7** (2026-10-01),
supporting PostgreSQL 13–18. **CVE-2026-3172**, a buffer overflow in parallel HNSW index
builds that could leak data from other relations or crash the server, was fixed in 0.8.2.
Anything older is a security floor violation rather than merely a stale pin.

Schema shape:

```sql
documents (id, source_path, filename, sha256, ingested_at, status)
chunks    (id, document_id FK, ordinal, text, embedding vector(768),
           tsv tsvector GENERATED)
```

## Consequences

**The dual-write problem ceases to exist,** and this is the decisive consequence rather
than performance. With two stores, ingesting a document means writing a registry row to
Postgres and vectors to Qdrant; if one succeeds and the other fails you get either a
document that is indexed nowhere or orphan vectors pointing at nothing. The real fixes
are an outbox table plus a relay, or a periodic reconciliation job, which is genuine
engineering that exists solely to paper over having two sources of truth. With pgvector:

```sql
BEGIN;
  INSERT INTO documents ...;
  DELETE FROM chunks WHERE document_id = $1;
  INSERT INTO chunks (document_id, text, embedding) ...;
COMMIT;
```

Either all of it happened or none of it did. See
[concepts/dual-write-problem.md](../concepts/dual-write-problem.md).

**Filtering is SQL.** Every vector database has a bespoke filter DSL and none can join.
Postgres gives the full query language over the real schema, joined against tables a
vector DB has never heard of. For requirement 4 it is not a close contest.

**One stateful system** to run, monitor, upgrade, back up and restore. `pg_dump` covers
the vectors, so there is one backup procedure and one restore drill rather than two.

**Three v1 bugs become unrepresentable,** which follows from modelling the data properly:

- listing and deleting documents was impossible because nothing recorded what existed
- stale chunks on re-ingest, since v1 IDs were `filename_chunk_i`, so same-named files
  collided and a shorter re-ingest left orphans. Now a `DELETE` inside the transaction
  handles it.
- duplicate uploads, since a unique index on `sha256` makes re-uploading the same bytes a
  detected no-op

**Accepted cost:** Postgres full-text search is genuinely weaker than BM25. `ts_rank` is
not BM25 and lacks its term saturation and document-length normalisation. This is
accepted until an eval set shows lexical ranking is the measurable limiter.

## Alternatives considered

**Qdrant.** Better ANN performance at scale, native sparse vectors for hybrid search,
quantization. It lost on the dual-write problem, on SQL filtering, and on being a second
service to operate, and its performance advantage is unreachable at 30k vectors. It would
become the right answer at millions of vectors with a single-purpose retrieval workload.

**Tantivy as a search service for real BM25.** Rejected, and this ADR records why the
proposal was bad. It was put in the design partly to create a second home for Rust, with
a justification reached for afterwards. Running it alongside Postgres reintroduces exactly
the dual-write problem argued against above, in exchange for relevance gains almost
certainly unmeasurable at this corpus size. That is bad engineering wearing a learning
objective as a disguise. Rust's justified home is the ingest worker; see
[0005](0005-postgres-as-the-queue.md) and [0001](0001-two-processes-not-three-services.md).

**ParadeDB `pg_search`,** real BM25 *inside* Postgres, built on Tantivy. Deferred rather
than rejected: it is the upgrade path if evals show lexical ranking is the limiter, and it
delivers Rust-grade search as an extension with no second service and no dual write.
Revisit with numbers rather than arguments. (Training-era knowledge; verify before use.)

**pgvector's weaker ANN accepted over ChromaDB continuity.** ChromaDB was also unpinned
and has broken its client/server API across versions before. No continuity worth keeping.
