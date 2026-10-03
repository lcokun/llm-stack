-- migrate:up
create extension if not exists vector;

create table conversations (
    id          uuid primary key default gen_random_uuid(),
    title       text,
    created_at  timestamptz not null default now()
);

create table messages (
    id               uuid primary key default gen_random_uuid(),
    conversation_id  uuid not null references conversations (id) on delete cascade,
    role             text not null check (role in ('system', 'user', 'assistant')),
    content          text not null,
    created_at       timestamptz not null default now()
);

create index on messages (conversation_id, created_at);


create table documents (
    id           uuid primary key default gen_random_uuid(),
    filename     text not null,
    source_path  text not null,
    sha256       text not null unique,
    status       text not null default 'pending'
                   check (status in ('pending', 'processing', 'ready', 'failed')),
    created_at   timestamptz not null default now(),
    ingested_at  timestamptz
);

create table chunks (
    id           uuid primary key default gen_random_uuid(),
    document_id  uuid not null references documents (id) on delete cascade,
    ordinal      int not null,
    text         text not null,
    embedding    vector(768),
    tsv          tsvector generated always as (to_tsvector('english', text)) stored,
    unique (document_id, ordinal)
);

create index on chunks using gin (tsv);

create table jobs (
    id            bigserial primary key,
    kind          text not null,
    payload       jsonb not null,
    state         text not null default 'queued'
                    check (state in ('queued', 'running', 'done', 'failed')),
    attempts      int not null default 0,
    max_attempts  int not null default 5,
    run_after     timestamptz not null default now(),
    locked_at     timestamptz,
    locked_by     text,
    last_error    text,
    created_at    timestamptz not null default now()
);

create index on jobs (run_after) where state = 'queued';

-- migrate:down
drop table if exists jobs;
drop table if exists chunks;
drop table if exists documents;
drop table if exists messages;
drop table if exists conversations;
drop extension if exists vector;

