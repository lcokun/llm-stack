# 0004 — Ollama now, behind an inference interface

- **Status:** accepted
- **Date:** 2026-10-03

## Context

v1 called Ollama directly from the bridge, with the URL in an environment variable and
the model names hardcoded as `CHAT_MODEL` / `VISION_MODEL`. The v2 design listed vLLM as
a later "model serving experience" upgrade, which needed scrutinising before it shaped
anything.

vLLM is fast for three reasons.

PagedAttention. The KV cache is the real memory bottleneck in serving. Naive
implementations allocate a contiguous block per sequence sized for the maximum length it
*might* reach, so a 200-token reply holds a 32k-token allocation. PagedAttention treats
the cache like OS virtual memory, using fixed-size non-contiguous blocks allocated on
demand, which fits far more concurrent sequences in the same VRAM.

Continuous batching. Scheduling happens per decode step rather than per batch, so
finished sequences leave immediately and new requests join at the next step.

Prefix caching. Shared prompt prefixes reuse their KV cache across requests.

All three optimise throughput under concurrency. This stack has one user with typically
one request in flight. Continuous batching has nothing to batch, and PagedAttention has
one sequence to page. Only prefix caching has any relevance, for a fixed RAG system
prompt, and llama.cpp has its own version.

The disqualifying constraint is simpler than performance. One vLLM process serves one
model, with no on-demand swapping. [0003](0003-native-multimodal-not-vision-chain.md)
needs a multimodal chat model, an embedding model, and cold-path access to a small VLM
and an abliterated alternative. On vLLM that is multiple processes each pre-allocating a
slice of 8188 MiB, and it does not fit. vLLM also does not do CPU offload, so a model
slightly too large fails to start rather than running slowly.

Ollama's on-demand load/unload is what makes a multi-model stack possible at all on this
hardware, so it is a genuine advantage here rather than a compromise.

## Decision

Use Ollama. Put all inference behind an interface:

```
InferenceClient
  ├── chat(messages, model, tools, stream)
  ├── embed(texts, model)
  └── capabilities(model)

implementations: OllamaClient · FakeClient (dev + CI) · later: LlamaCppClient, VLLMClient
```

The interface is what makes the fake server for CI possible, what lets the eval harness
A/B two backends on identical inputs, and what turns trying vLLM into a weekend
experiment instead of a migration.

Pin the Ollama image tag. v1 used bare `ollama/ollama`.

## Consequences

- `FakeClient` is the primary development target. With the workstation's 32 GB RTX 5000
  Ada rented out, most work happens against a fake inference server and real-model work
  gets its own sessions. This is a constraint-driven benefit: CI never needs a GPU.
- Model names stop being environment constants and become registry entries with declared
  capabilities, per [0003](0003-native-multimodal-not-vision-chain.md).
- The interface is one of exactly three deliberate seams in the architecture. See the
  note in [0005](0005-postgres-as-the-queue.md).
- Accepted cost: an abstraction layer over a single implementation is speculative
  generality until the second implementation exists. Justified here because the second
  implementation (`FakeClient`) is needed immediately for CI, so the seam pays for itself
  on day one rather than on promise.

## Alternatives considered

**vLLM now.** Rejected. Its three advantages are all throughput-under-concurrency with
one user; one-process-one-model does not fit a multi-model stack on 8 GB; no CPU offload
means slightly-too-large fails rather than degrades; and the ready-made quant ecosystem
for AWQ/GPTQ is thinner than GGUF's. It becomes right with genuine concurrency, a single
model serving everything, and VRAM headroom, the natural home being the workstation's
32 GB card if it returns from rent.

**llama.cpp server directly**, skipping Ollama's wrapper. Deferred rather than rejected,
and the most interesting finding of this review. It offers grammar-constrained decoding
(GBNF) which makes the model *unable* to emit invalid JSON. For reliable tool calling,
especially with a weak or abliterated model, that targets this stack's actual bottleneck
of single-stream latency and output validity rather than vLLM's. Ollama exposes a coarse
version via `format: json`. Revisit when tool-call reliability becomes the limiter.

**ExLlamaV2.** Deferred. Genuinely faster than llama.cpp for single-user inference on
consumer GPUs with EXL2 quants. Same category as above, since it targets the right
bottleneck. Costs the Ollama model-management convenience.

**TGI, SGLang.** Not evaluated in depth; same niche as vLLM, same objection.

**Call Ollama directly with no interface.** Rejected. It blocks a fake backend for CI,
which blocks testing without a GPU, which blocks CI entirely.

*(vLLM, llama.cpp, ExLlamaV2 and SGLang details are training-era knowledge, unverified
as of 2026-10-03. Verify before adopting any of them.)*
