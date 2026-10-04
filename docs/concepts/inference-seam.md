# The inference seam

**Short version:** `InferenceClient` is a Protocol with three methods, and the point of it
is that `OllamaClient` arrived without changing a line of `ChatService`. Parity is one
test suite run against both backends, asserting only what a real model can honestly
promise.

## What the seam cost, and what it bought

[ADR 0004](../decisions/0004-ollama-behind-an-inference-interface.md) put Ollama behind an
interface before Ollama existed in the codebase. The cost was `FakeClient`: a hash-based
stand-in that echoes its input, roughly 60 lines that ship no features.

The payoff showed up twice. CI has no GPU and never needs one, so the suite is
deterministic and runs in seconds. And when the real backend landed, the diff touched one
new module plus four lines of wiring. `ChatService`, the routes, and the SSE translation
were untouched, because none of them had ever named a backend.

## Two streaming formats, one translation

Ollama streams NDJSON: one JSON object per line, no framing, no event names.

```json
{"message":{"role":"assistant","content":" hello"},"done":false}
{"message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","eval_count":186}
```

The browser needs SSE, which is `data: ` prefixes and blank-line separators. Those are
different formats for the same job, and the service translates between them exactly once:
`OllamaClient.chat` turns NDJSON lines into plain string fragments, and
[routes.py](../../services/core/src/llm_stack_api/routes.py) turns fragments into SSE
events. Nothing in the middle knows either format, which is why swapping a backend does
not reach the browser. See
[streaming-ndjson-sse-websockets.md](streaming-ndjson-sse-websockets.md).

The final chunk carries `eval_count`, `prompt_eval_count` and `eval_duration`. Those are
real token counts, better than anything the metrics currently record, and they are
deliberately dropped for now: tokens become a metric when something needs them.

## Capabilities come from /api/show

`POST /api/show` returns what a model can do:

| Model | `capabilities` |
|---|---|
| `qwen3:4b` | `["completion", "tools", "thinking"]` |
| `nomic-embed-text` | `["embedding"]` |

That is what makes `chat()` able to reject an embedding model and `embed()` able to reject
a chat model, matching `FakeClient` without a hardcoded table. It costs one extra request
the first time a model is used, cached for the life of the process, so a model re-pulled
with different capabilities needs a restart to be noticed.

One trap sits in the dimensions. `model_info` holds an architecture-prefixed key:

```
"nomic-bert.embedding_length": 768
```

Chat models have the same key, where it means hidden size rather than vector width.
Reading it unconditionally makes every chat model claim to be an embedding model, so it is
read only when `embedding` is among the declared capabilities.

## `think: true` is the setting that stops the rambling

Qwen3 is a hybrid reasoning model. Asked for one word with `think: false`, it produced
roughly 400 tokens of visible deliberation, in `message.content`, where a user would see
it. With `think: true` the same prompt put the reasoning in `message.thinking` and left
`content` holding `hello`.

The setting that reads backwards is the one that works. `think: false` asks the template
not to emit a reasoning block; the model reasons anyway, as ordinary prose, and there is no block
for Ollama to separate out. `think: true` gives it a channel, and the client streams
`content` while ignoring `thinking`.

It is sent only for models that declare the `thinking` capability, which is the second
thing the `/api/show` lookup pays for.

## Timeouts and resource ownership

httpx applies a five second timeout to connecting, reading, writing and pool acquisition
alike. Both halves of that are wrong here: a cold model took 2.77s to load before its
first token, and a long reply streams for minutes. The client sets `read=300.0`, which on
a streaming response bounds the gap *between* chunks rather than the whole stream.

The client takes an `httpx.AsyncClient` rather than building one from a URL. A client that
owns a connection pool also has to be closed, and lifetime management does not belong
inside an inference interface. The app's lifespan registers the cleanup on an
`AsyncExitStack`, which unwinds in reverse order however the block exits. That matters
because the transport is conditional: only one of the two backends has one.

## What parity actually asserts

`test_inference_contract.py` is parametrised over backends, so every contract test runs
twice. Eleven tests, 22 results, and when nothing answers on port 11434 the Ollama half
skips with a reason printed rather than failing.

What moved into it is everything true of any backend: streams arrive as fragments,
validation is deferred until iteration, an empty message list raises, an embedding model
cannot chat, embeddings come back one vector per input, an unknown model raises
`UnknownModelError`.

What stayed in `test_fake_client.py` is everything only the fake promises. Determinism is
a property of a hash function. Unit-norm vectors are a choice `_unit_vector` makes, and
asserting them of nomic would be testing the vendor. The exact echo text is the fake's
entire purpose.

So the shared assertions are deliberately weak. `"".join(fragments).strip()` being
non-empty is all a model can be held to. The moment a test asserts *what* a model said it
has become an eval, and evals belong in phase 5b with recall and nDCG attached.

Two mechanics make this work. Model names come from `OLLAMA_CHAT_MODEL` and
`OLLAMA_EMBED_MODEL`, not from `Settings`, because conftest pins `Settings` to the fake.
And the skip lives inside the fixture: probing availability at import time would make the
collected test count depend on the network, so the same file would quietly collect
different numbers of tests on different machines with no `s` in the output to explain it.

## The suite must not inherit `.env`

`just test` loads `.env`, so pointing `INFERENCE_BACKEND` at Ollama for manual work ran
the entire suite against a GPU model: two failures asserting the fake's echo text, and
every chat test three seconds slower.

`pytest_configure` in conftest now pins `INFERENCE_BACKEND`, `CHAT_MODEL` and
`EMBEDDING_MODEL` to the fake for the whole session. It is a hook rather than a fixture,
so it is registered by its reserved name and takes no decorator, and it runs before
collection. `get_settings` is `lru_cache`d, so the pin also clears that cache.

> A test suite that behaves differently depending on a developer's local config is not a
> gate.

## What this does not give us

**Nothing chooses a model.** `capabilities()` answers questions about one named model; nothing
chooses a model, and prefix routing is still how requests find one. The registry and tool
calling are phase 6.

**Generation options are not exposed.** Temperature, `num_predict`, context length and seed are not
exposed through the seam, so a runaway reasoning model cannot be capped from the API. That
becomes necessary when retrieval tuning starts.

**The mid-stream error path is inferred.** Ollama's documentation does not describe what a
mid-stream failure looks like, and the client handles it by raising `OllamaError` on any
chunk carrying an `error` key. That path is inferred rather than verified.

**The model itself is unjudged.** `qwen3:4b` burned 186 evaluation tokens to answer
`hello`. Whether that is acceptable is something to measure, which is why the default chat
model is a phase 5b decision.
