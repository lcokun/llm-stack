# Ids and ordering

**Short version:** `now()` returns transaction start time, so it cannot order rows written
in one transaction. UUIDv7 puts the clock inside the id, which fixes ordering and index
locality at the same time.

## The bug this came from

`messages.created_at` defaulted to `now()`, and the store read them back with
`order by created_at, id`. A test inserted three messages and asked for them in order:

```
assert ['one', 'three', 'two'] == ['one', 'two', 'three']
```

All three rows were written inside one transaction, so all three had an identical
`created_at`. The tiebreak fell to `id`, which was a random UUIDv4, so the order was
whatever the random bytes happened to sort to.

Nothing about the SQL looked wrong, and on a workload where each message arrived in its
own transaction it would have behaved for months.

## Postgres has four clocks

| Function | Returns |
|---|---|
| `now()`, `transaction_timestamp()` | when the transaction began; constant within it |
| `statement_timestamp()` | when the current statement began |
| `clock_timestamp()` | actual wall clock, advances mid-statement |
| `timeofday()` | like `clock_timestamp()` but a text string |

`now()` being constant is a feature. It means every row written by one transaction agrees
on when that transaction happened, which is what you want for an audit trail and what
makes `created_at` comparable across tables. It also means `created_at` is useless as an
ordering key for rows written together.

Switching the default to `clock_timestamp()` would produce distinct values, but only
*approximately* distinct. Two inserts in the same microsecond still collide, and the
tiebreak problem comes back on a schedule that only shows up under load.

## Why the id tiebreak did not help

A UUIDv4 is 122 random bits. Sorting by it is sorting by noise. Adding `, id` to an
`order by` feels like a safety net and provides none when the leading key ties.

A tiebreak only works if the tiebreak column itself carries order.

## UUIDv7

RFC 9562 defines a UUID whose high 48 bits are a Unix millisecond timestamp, with counter
bits below it to keep values increasing within the same millisecond. Postgres 18 has
`uuidv7()` built in, alongside `uuidv4()` and the older `gen_random_uuid()`.

Verified on this database: 5000 values generated inside a single transaction came back
strictly increasing. So `order by id` is a total order that matches insertion order, and
the tiebreak problem stops existing rather than becoming rarer.

```sql
alter table messages alter column id set default uuidv7();
```

```sql
select id, conversation_id, role, content, created_at
from messages
where conversation_id = %s
order by id
```

## The part that is not about ordering

Random primary keys scatter inserts uniformly across a B-tree. Every write dirties a page
somewhere different, so the working set is the whole index and the cache hit rate falls as
the table grows.

Time-ordered keys append near the right edge of the tree. Inserts touch a small number of
pages, which stay hot. On a table of a few thousand rows this is unmeasurable; on millions
it is the difference between an index that fits in cache and one that does not.

That is why this project switched all four uuid primary keys rather than only `messages`.
The ordering bug was in one table; the locality argument applies to every table, and the
change costs one migration while they are all empty.

## What it does not fix

**Rows created before the change keep their old ids.** A table holding both v4 and v7 ids
is not ordered by id for the v4 rows. Here that cost nothing, because no durable rows
existed yet. In a deployed system this needs a backfill plan, and a backfill of primary
keys means rewriting every foreign key that points at them.

**Ids become guessable in time.** A v7 id leaks roughly when the row was created, and
sequential-looking ids invite enumeration. Neither matters for a single-operator service
behind Tailscale, but an id exposed to the public is a different decision.

**Ordering still has to be asked for.** Postgres returns rows in whatever order it finds
convenient unless you write `order by`. A query that happens to come back sorted today
will stop doing so when the planner picks a different scan.

## The general rule

> An ordering key has to be something the database guarantees is ordered.

Not a timestamp that might tie, not a random id that reads like a tiebreak, and not the
order rows happen to come back in. If order is part of the contract, something in the
schema has to make it true, and a test has to assert it.
