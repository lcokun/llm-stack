# Git workflow

**Short version:** `main` is protected, every change arrives through a pull request, and
tags are the only immutable refs in the repo. Solo makes this feel absurd for about a
week, and then it becomes how the work happens.

## Why bother when there is one operator

CI needs somewhere to be a gate. A test suite that runs after the code is already on
`main` can only tell you that you already broke it, which makes the ops-complete goal in
PLAN.md meaningless. A required status check on a pull request is the one arrangement
where CI can actually refuse.

`main` becomes a branch you can trust. If every commit on it arrived green through a pull
request, then "`main` works" is a fact you can lean on for a deploy, for a bisect, or for
coming back after six weeks. Push directly once and it degrades to "`main` probably
works."

The history is also the portfolio. The repo is public and pinned, and small labelled
commits merged through reviewed pull requests read differently from 200 commits of `wip`
on `main`.

## Tags

A tag is a name for one commit, and in this repo it is the only ref that never moves.
Branches move constantly; tags are the fixed points you can always get back to.

Use annotated tags (`git tag -a`) rather than lightweight ones. A lightweight tag is just
a file containing a SHA, while an annotated tag is a real object in the database with an
author, a date and a message. So `git show v1-legacy` tells you why the tag exists, and
`git describe` prefers them.

Two things that catch people out:

- Tagging ignores your working tree, because a tag names a commit. Uncommitted changes
  sitting in the working directory are irrelevant to it, which is what made it safe to tag
  `v1-legacy` at the current `main` while a pile of unstaged v2 docs was still open.
- Tags do not travel with `git push`. They need `git push origin <tag>` explicitly, and a
  tag that exists only locally protects nothing, because the thing it protects against is
  losing the local machine.

`v1-legacy` is load-bearing: it is the reason deleting v1's code is safe rather than
destructive. See [ADR 0008](../decisions/0008-monorepo-layout.md).

## Branches

Short-lived, named `<type>/<slug>` using the same types as commit messages, so
`docs/v2-design`, `feat/postgres-queue`, `fix/stale-lock-reaper`.

Short-lived means days. A long branch rots: `main` moves underneath it, every day adds
conflict surface, and the merge becomes an event you dread. ADR 0008 killed the
long-lived `v2` branch for exactly this reason, since with nothing maintained in parallel
a months-long branch is `main` wearing a disguise.

Rebase onto `main` before merging, so history stays linear and `git log` reads as a
sequence of changes rather than a braid.

## Commits

Format is `<type>: <description>`, where type is one of `feat`, `fix`, `refactor`,
`chore`, `docs`, `test`, `perf`. Imperative, lowercase, no trailing period.

One logical change per commit. The test is whether you can describe it without "and": if
a commit adds the migration, fixes a typo and bumps a pin, it is three commits. The
payoff is that `git revert` becomes a precision instrument and `git bisect` can name the
actual culprit.

The tool for this is `git add -p`, which walks the diff hunk by hunk and asks whether each
one belongs in this commit. Without it you commit whatever happened to be on disk.

Write the body for the *why*. The diff already says what changed; it cannot say what you
were trying to achieve or what you ruled out.

## What never happens

- No rewriting published history. Once a commit is on `main` and pushed it is permanent,
  so fix forward with a new commit or `git revert` instead of amending or rebasing it away.
- No force-push to `main`. The ruleset enforces this, which is the point of turning
  protection on rather than just intending it.
- Force-push only your own unmerged branch, and only with `--force-with-lease`. Plain
  `--force` overwrites the remote unconditionally, including work you have not seen, while
  `--force-with-lease` refuses if the remote moved since you last fetched. Nothing in this
  repo calls for bare `--force`.
- No secrets. `.gitignore` covers `.env` and `.env.*` with `!.env.example` as the escape
  hatch for the documented template. A secret that lands in a commit is in the history
  permanently and must be *rotated*, since removing the file in a later commit does
  nothing. The SearXNG secret in phase 6 is the first real instance.

## Who runs git here

Mel does. Claude prints the exact command lines and stops. A tag, branch or commit does
not exist until Mel says it does, so it is never inferred from a plan or confirmed by
running `git` to peek. This is a rule in the repo-local instructions file, and it exists
because the one thing worse than a bad commit is a commit nobody remembers making.
