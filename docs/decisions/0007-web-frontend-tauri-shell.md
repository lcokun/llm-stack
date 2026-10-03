# 0007 — One web frontend, served now, shelled in Tauri later

- **Status:** accepted
- **Date:** 2026-10-03

## Context

[0006](0006-own-api-plus-openai-compat.md) retires `oterm`, so v2 needs a client. Mel's
stated position: a web UI risks "being stuck with web stuff"; a TUI is fine personally
but "not many will wanna use a TUI" and the goal includes simulating production; the
preference is a lightweight app that does not depend on Electron.

The UI has to do chat with token streaming; a model picker showing capabilities from the
registry so "this one cannot see images" is visible rather than a mystery; image paste
and drop; document upload with job progress, which only exists because of
[0005](0005-postgres-as-the-queue.md); document list and delete; and clickable citations
resolving to the source chunk and page. The last three are inherently visual: a
filterable list, a progress bar, a citation that opens a PDF page.

The decisive technical point is that a chat UI is a rich-text document renderer.
Markdown, syntax-highlighted code blocks, inline images, streaming text that reflows as
it arrives, selectable and copyable history. That is the single thing browsers are
world-class at and the weakest area of every native GUI toolkit. A pure-Rust UI means
hand-rolling text layout, markdown rendering, syntax highlighting, image embedding, text
selection and scrollback before displaying one useful message.

A common assumption also needs correcting: Tauri is a web frontend in a native shell with
a Rust backend. It escapes Electron while still being HTML, CSS and JS, so it does not
avoid web work.

## Decision

One plain static frontend, talking to the API over HTTP, shipped to two targets. Served
by the gateway it is a web app reachable across the Tailnet; wrapped in Tauri it is a
desktop app with a native window.

Same frontend code, both targets, nothing discarded. This is the intended use of Tauri;
the shell is a shell.

Ship the web target first (phase 3) because it costs nothing extra and makes progress
visible immediately. Add the Tauri shell as a deliberate later phase (9).

Use vanilla JS for the phase 3 spike. One chat page with SSE streaming is within reach,
and the gap frameworks fill becomes concrete by being felt. The framework decision is
deferred to phase 6, when the spike's limits are known, between Svelte as the gentler
on-ramp that compiles away and React as the better CV line and larger ecosystem.

The Rust TUI is dropped.

## Consequences

**Tauri is where "simulating prod" gets real**, and this is its strongest justification.
A web UI on localhost teaches nothing about shipping software to people. The Tauri phase
teaches packaging (`.deb`, AppImage, `.msi`, `.dmg`), cross-platform CI with a build
matrix because a target can only be built on that target, code signing and why unsigned
binaries get blocked, auto-update with an update server and signed manifests, and native
integration covering file dialogs, drag-and-drop, tray and OS notifications. None of that
is reachable from a browser tab or a TUI.

**It is load-bearing Rust.** Rust ends with two honest homes: the ingest worker
([0005](0005-postgres-as-the-queue.md)) and the app shell. That is enough.

**Verified 2026-10-03:** Tauri **2.11.5**, using **WebKitGTK 4.1** on Linux. WebKitGTK
means rendering differs from Chrome, so the frontend must be tested in the actual shell
rather than assumed from browser behaviour.

**It forces the case-sensitivity discipline.** macOS and Windows CI runners will clone
this repo, so no two tracked files may differ only by case. Local-only working files are
therefore named distinctly and gitignored rather than being case variants of tracked ones.

**Auth gets harder.** API keys in a header suffice for `curl`; a browser needs sessions,
cookies, CSRF consideration and a login flow. This is the main reason the gateway's auth
work cannot be deferred indefinitely.

**A PWA is a nearly free intermediate step,** installable as its own window with no
packaging work once the web UI exists. Less instructive than Tauri, available months
earlier.

**The spike must graduate.** The web UI is labelled a spike through phases 3–5 and
becomes real in phase 6, alongside citations and tool calls. The repo-local instructions
carry the enforcement duty, and it is time-boxed rather than open-ended precisely because
the UI is the only client.

**Accepted cost:** roughly two to three weeks of frontend work, and the frontend
competence that comes with it. That is reframed rather than avoided, since every eval
viewer, internal dashboard and admin panel is a web page, making this table stakes rather
than a specialisation, and the scope here is a chat view, a documents view and a model
picker.

## Alternatives considered

**Web UI only, no desktop app.** Rejected on Mel's stated goal of simulating production
delivery. Also forgoes the packaging and distribution learning, which is a real gap for
an ops-complete objective.

**TUI only.** Rejected. Legitimate for Mel personally, as a terminal-first user with
`ytm-cli` already built, but it cannot present citations, document lists or job progress
well, and it is the wrong artifact for anyone else.

**Rust TUI as the Rust on-ramp.** Rejected, and this records why the original proposal
failed its own test. It was placed in the design to create a slot for Rust. With a web
frontend as the real client a TUI is ornamental, which is the same objection that killed
Tantivy in [0002](0002-postgres-pgvector-not-qdrant.md). The on-ramp problem solves
itself: step one of the worker ladder, reading a file, chunking it and printing it with
no network and no async, is already a gentle Rust introduction. Revisit only if Mel finds
they genuinely resent opening a browser, at which point it is justified by use rather
than by needing a slot.

**egui / iced / gtk4-rs / slint.** Rejected for this application. egui is excellent for
dashboards and tool panels but has basic text, so rich markdown is a project in itself
and it does not look native. iced is more app-shaped but still maturing and has the same
text problem. gtk4-rs would look correct under Hyprland but GObject from Rust is awkward
and rich text remains manual. slint is polished but aimed at embedded and kiosk UIs and
needs a licence check. All four lose on the rich-text argument rather than on Rust.

**Electron.** Rejected per Mel's explicit constraint, and on bundle size.

*(Framework and toolkit maturity claims other than the verified Tauri version are
training-era and unverified.)*
