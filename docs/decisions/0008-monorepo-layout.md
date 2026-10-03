# 0008 — Same repo, polyglot monorepo layout

- **Status:** accepted
- **Date:** 2026-10-03

## Context

v2 is a greenfield rewrite of code that already exists in this repository, in four
languages (Python, Go, Rust, JS), with a public GitHub remote that is pinned on Mel's
profile. Three questions needed answering before any file moved: where the new code
lives relative to the old, how a four-toolchain repo is laid out, and who owns the
database schema when more than one service reads it.

## Decision

### Same repository, old code tagged then deleted

Mel chose a greenfield rewrite but not a new identity. The history showing *hack → audit
→ principled rewrite* is worth more than a clean slate, and one polyglot monorepo reads
better on a pinned profile than three thin repos.

Tag `v1-legacy` before deleting anything, then delete the old code in one labelled
commit. The tag makes v1 recoverable with one command, so keeping dead files around buys
nothing and violates the project's own no-dead-code rule. Running v1 again is a
`git worktree` off the tag rather than a directory on `main`.

Confirmed 2026-10-03: the v1 stack is idle and unused, so deletion timing is
unconstrained and no migration path off it is needed.

### Layout

```
llm-stack/
├── justfile                  # single entry point for all four toolchains
├── PLAN.md
├── compose.yml               # dev
├── compose.prod.yml
├── .github/workflows/        # path-filtered per service
│
├── api/                      # THE CONTRACT: openapi.yaml, shared schemas
│
├── services/
│   ├── gateway/              # Go
│   ├── core/                 # Python: api/ ÷ core/ split inside
│   └── worker/               # Rust
│
├── apps/
│   ├── web/                  # static frontend
│   └── desktop/              # Tauri shell (phase 9)
│
├── db/migrations/            # SQL, owned by the repo not a service
│
├── deploy/                   # systemd units, Caddy, searxng config
│
└── docs/
    ├── decisions/            # these ADRs
    ├── concepts/             # learning notes
    └── runbooks/             # "the worker is stuck, now what"
```

### Migrations are owned by the repo, not a service

Both Python core and the Rust worker read and write the same tables. If each ran
migrations on startup there would be a race on every deploy and two sources of truth for
the schema. Migrations are therefore a standalone deploy step: one tool, run by CI before
services start, living at `db/migrations/`.

No service runs migrations on startup. This is the rule, and getting it wrong is a nasty
class of outage.

### `justfile` as the single entry point

Four toolchains (`uv`, `go`, `cargo`, `npm`) and nobody should need all four in their
head to work on the repo. `just dev`, `just test`, `just lint`, `just migrate`. On a
polyglot monorepo this is what separates a project that can be returned to after six
weeks from one that has to be re-learned.

### Protected `main`, short-lived branches, PRs with CI as a gate

Even solo. It feels absurd for about a week and then becomes how the work happens. It
gives CI somewhere to be a gate rather than a decoration, which it must be for the
ops-complete goal to mean anything, and the discipline is visible in the repo's history.

This supersedes earlier advice to use a long-lived `v2` branch. With nothing being
maintained in parallel, a months-long branch is `main` wearing a disguise, and long
branches rot.

### Case-sensitivity discipline

No two tracked files may differ only by case. macOS and Windows CI runners will clone
this repo for the phase 9 Tauri builds, and checkout breaks on case-insensitive
filesystems. Local-only working files are therefore given distinct names and gitignored,
rather than being case variants of tracked ones.

## Consequences

- `api/` at the root is "contracts first" made physical. It is also what the Go client
  and TypeScript types get generated from, so three sides cannot silently disagree, and
  it is what makes the phase 2 Go extraction mechanical.
- Path-filtered CI keeps the feedback loop short, so touching Rust does not run the
  Python suite.
- One version for the whole stack, tagged. Simplest for a single-box deployment.
- Monorepo costs accepted: the repo grows, and CI needs path filtering to stay fast. Both
  are fine at this scale, and the benefit of changing the contract and both sides of it
  in one atomic commit is exactly what this project needs.
- **Git is never executed by Claude in this repository.** Command lines are printed for
  Mel to run, including tags, branches and pushes. A tag or branch is not treated as
  existing until Mel confirms it. Recorded in the repo-local instructions file.
- The README must never describe software that does not exist. The repo is public, so an
  interim README lands with the deletion rather than after it.

## Alternatives considered

**A new repository.** Rejected by Mel. Would have discarded the history that makes the
rewrite legible, and split the portfolio artifact in two.

**Separate repositories per service.** Rejected. Three languages with one shared
contract means every contract change becomes a cross-repo coordination problem, and
atomic commits across the API and its consumers become impossible. That cost buys
independent deployability, which a single-box single-operator stack does not need.

**Old code kept alongside the new in a `v1/` directory.** Rejected. It is dead code by
definition, the tag already preserves it, and it would be the first thing a visitor to a
public repo trips over.

**Long-lived `v2` branch.** Rejected, as above.

**Each service owning its own migrations.** Rejected. Two services, two languages, one
schema; a startup race and two truths. The standalone step is the pattern once more than
one language touches a database.

**Nix or Bazel for the polyglot build.** Not adopted. A `justfile` plus each language's
native tooling is sufficient at this scale, and both alternatives are a significant
learning project in their own right that would compete with the actual goals.
