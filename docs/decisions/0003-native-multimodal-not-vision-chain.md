# 0003 — Native multimodal chat, not a vision chain

- **Status:** accepted
- **Date:** 2026-10-03

## Context

v1 chained two models. In `bridge.py`, if the last user message carried images, the
bridge sent text *and* image to `llama3.2-vision:11b`, took the text response back,
called `pop("images")` to discard the image, prepended `[Image description: ...]`, and
forwarded to `mannix/llama3.1-8b-abliterated`.

The chain existed because the chat model was abliterated and therefore text-only. Four
things are wrong with it.

It launders a correct answer through a blind model. The vision model received the
question as well as the image, so its output was frequently already the answer. Handing
that to a text model which cannot see the image gives paraphrase at best and
embellishment at worst, which is hallucination with extra steps.

Follow-up turns are blind. Turn one works. On turn two the user asks "what does the label
in the bottom-left say?" without resending the image, so `last_user` has no `images`, no
vision call happens at all, and the model answers from a description written for a
different question. The image is gone, because nothing stored it. Nothing in the stack
could ever look at it again.

It does not reliably achieve its own purpose. The vision model is an ordinary aligned
model and runs *first*. If it declines to describe something, the chain fails at step one
and the uncensored model downstream never gets the chance. The refusal point sits upstream
of the refusal removal.

The hardware makes it painful. Chat ~5 GB, vision ~8 GB, card 8188 MiB. They cannot
co-reside, so every image message meant unloading chat, loading 8 GB of vision, inferring,
unloading, reloading chat, and inferring again. Tens of seconds of model loading before
any thinking.

Two smaller defects: `result["message"]["content"]` raised `KeyError` on any error
response, surfacing as a bare 500; and only `/api/chat` was enriched, so `/api/generate`
and `/v1/*` had no vision at all.

Mel's requirements, stated 2026-10-03: abliteration is nice to have rather than core, so
it should be a selectable alternative rather than the default. Vision is for both
documents and screenshots and for general image Q&A.

## Decision

The preprocessing chain dies. Replace it with a model registry that declares
capabilities, and let capability decide the strategy per request:

```
qwen3-vl-8b        vision: native   tools: native   default
llama3.1-ablit     vision: none     tools: weak     uncensored alternative
nomic-embed-text   embeddings only, 768 dims
```

- A model with native vision gets the image passed straight through. No chain, no swap,
  no laundering, and it attends to the region the question is about.
- A model with no vision gets `inspect_image(image_id, question)` exposed as a tool,
  callable as many times as the conversation needs.

"Selectable alternative" becomes a routing problem rather than a hardcoded `CHAT_MODEL`,
with no `if model == "..."` scattered through the code. The vision tool is the capability
fallback, and the abliterated model is precisely the client that needs it.

Stop discarding images. Store the file, reference it by ID in the conversation, keep it
available for later turns. This requires the database from
[0002](0002-postgres-pgvector-not-qdrant.md); in v1 there was nowhere to put it, so the
only expressible architecture was the lossy one.

Images become an ingest input as well as a chat input. Screenshots, scanned pages and
charts belong in the corpus: image → OCR and VLM description → text → chunk → embed, with
the original retained and referenced.

Run OCR and the VLM together rather than choosing between them. A VLM asked to describe a
screenshot of an error will paraphrase it, while OCR gives the literal string, which is
what you need when the answer is an exact error code or version number. The VLM gives
layout and semantics, such as "a bar chart comparing Q1 to Q4", which OCR cannot. Store
both.

## Consequences

**Revised VRAM budget, and it changes the design.** Verification on 2026-10-03 showed a
native multimodal model costs ~6–6.6 GB at Q4 rather than the ~4.4 GB first assumed. On
8188 MiB that fits one multimodal model plus the embedding model (~274 MB), with no room
for a second resident VLM. So `inspect_image` and the abliterated alternative are
explicitly cold swap-on-demand paths. The hot path has no swapping at all, which is the
single biggest UX improvement over v1. See
[concepts/vram-budget.md](../concepts/vram-budget.md).

**Model choice gets decided by evals rather than argument.** Abliteration measurably
degrades instruction-following and structured tool calling, which is the exact capability
this architecture depends on. That is a real conflict, so it gets measured: the same eval
set across abliterated-plus-chain versus a current native multimodal model, scoring
retrieval accuracy, tool-call success, and the refusal cases that actually matter to Mel.
This is the first real customer of the eval harness.

**A bug surfaced by the document requirement.** `read_pdf` was
`"\n".join(page.get_text() for page in doc)`. A scanned PDF or a PDF of screenshots has
no text layer, so it returned `""`, chunked to nothing, and reported success with 0
chunks. Document ingestion silently failed on exactly the documents Mel cares about. The
fix is structural and per-page rather than per-document, since real PDFs mix both:
extract the text layer, and where it is sparse relative to page count, render the page and
send it down the OCR and VLM path.

**Eval set must include document-vision cases:** a scanned page, a screenshot containing
code or an error, a chart requiring numbers read off it, and a photo for the general case.
Those four cover the failure modes that matter.

**Scope cost, accepted.** OCR, page-level routing, an asset store and image-aware
retrieval are real work. Staged: text documents first, image path in the worker's second
iteration.

**Storage:** originals on a disk volume; Postgres holds path, SHA-256, MIME type and
metadata, but not the bytes. Postgres can store binaries but it bloats dumps and slows
restore for no benefit. MinIO is the eventual version and is deferred as another service.

## Alternatives considered

**Keep the chain, fix the errors.** Rejected. The lossiness is structural rather than a
bug, and one-shot description with no ability to re-query cannot be patched.

**Native multimodal only, drop the vision tool.** Rejected because Mel wants abliteration
available, and a text-only model needs the tool path to see anything. One mechanism
serving both models is cheaper than two code paths.

**Keep a small resident VLM alongside the chat model** so the tool path is hot. Rejected
on the revised VRAM budget, since 6.6 GB plus 2 GB plus embeddings does not fit in
8188 MiB. Revisit if the workstation's 32 GB card returns from rent.

**Keep `llama3.2-vision:11b`.** Rejected. Verified candidates (Qwen3-VL-8B ~6 GB @ Q4,
reportedly strongest small model at document reading; Qwen3.5-9B Q4_K_M 6.6 GB, Apache
2.0, native vision + tools; Gemma 4 native vision at every size) outclass it for document
work. Model names come from secondary sources, so verify against ollama.com before
pulling.
