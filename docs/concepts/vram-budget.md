# The VRAM budget

**Short version:** context length costs as much as weights do, and that surprises people.
On this laptop the ceiling is one multimodal model plus embeddings.

## The hardware

```
NVIDIA GeForce RTX 4070 Laptop GPU — 8188 MiB
```

Call it ~7.5 GB usable; the display and driver take a slice. The workstation's RTX 5000
Ada (32 GB) is rented out, so this is the dev box.

## What occupies VRAM

Two things, and people only think about the first.

### Weights

Quantization is what makes an 8B model fit at all. Rough sizes for a 7–8B model:

| Quant | Size |
|---|---|
| Q4_K_M | ~4.4 GB |
| Q5_K_M | ~5.3 GB |
| Q8 | ~7.5 GB |
| fp16 | ~15 GB |

### The KV cache

This is the part that gets forgotten. Every token in the context stores a key and value
vector per layer, and that memory is held for the whole conversation. The formula:

```
bytes per token = 2 × layers × kv_heads × head_dim × bytes_per_element
```

The leading `2` is for K and V. Worked for a Llama-3-8B-shaped model with 32 layers, 8 KV
heads under GQA, head dim 128, fp16:

```
2 × 32 × 8 × 128 × 2 = 131,072 bytes = 128 KiB per token
```

So:

| Context | KV cache |
|---|---|
| 8k | ~1.0 GB |
| 16k | ~2.0 GB |
| 32k | ~4.0 GB |
| 128k | ~16 GB |

Grouped Query Attention is doing a lot of work in those numbers. That model has 32
attention heads but only 8 KV heads, so the cache is a quarter of what multi-head
attention would need. Pre-GQA models at 32k context are simply not runnable on 8 GB.

## The budget, and why the plan changed

The first version of the v2 plan assumed a ~4.4 GB chat model and a small resident VLM
alongside it. Verification on 2026-10-03 showed native multimodal models cost more:
Qwen3-VL-8B is ~6 GB at Q4, Qwen3.5-9B about 6.6 GB at Q4_K_M. *(Secondary sources;
verify against ollama.com before pulling.)*

Which gives:

| | VRAM |
|---|---|
| native multimodal chat model @ Q4 | ~6.0–6.6 GB |
| KV cache @ 8k | ~1.0 GB |
| `nomic-embed-text` | ~0.3 GB |
| **total** | **~7.3–7.9 GB** |
| available | ~7.5 GB |

That is the ceiling: one multimodal model plus embeddings, at modest context, with no
room for a second resident VLM.

Which is why [ADR 0003](../decisions/0003-native-multimodal-not-vision-chain.md) makes the
`inspect_image` tool and the abliterated alternative explicit cold swap-on-demand paths.
The hot path has no model swapping at all, which is the biggest single UX improvement over
v1.

## What v1 did, for contrast

Chat (~5 GB) and vision (~8 GB) cannot co-reside in 8188 MiB. So every image message
unloaded chat, loaded 8 GB of vision from disk, inferred, unloaded it, reloaded 5 GB of
chat, and inferred again. Tens of seconds of pure model loading before any thinking
happened. It was invisible on the 32 GB workstation and the worst thing about the stack
on the laptop.

## Practical consequences

Context length is a budget line that you pay for. Advertising 128k context is meaningless
if the cache for it does not fit, and choosing 32k over 8k costs ~3 GB, roughly
two-thirds of a quantized model.

KV cache quantization is the lever if long context is genuinely needed. Caching at 8 bits
instead of 16 halves it, at some quality cost. Measure before assuming that cost is
acceptable.

Model swapping is a latency cliff. Loading 6 GB from disk takes seconds to tens of
seconds, so architect the hot path never to swap and treat anything that does as a cold
path with a user-visible wait.

`FakeClient` exists because of all this. With one model's worth of headroom, most
development runs against a fake inference server
([ADR 0004](../decisions/0004-ollama-behind-an-inference-interface.md)) and real-model
work gets dedicated sessions. It also means CI never needs a GPU.

## Sanity-checking a model before pulling it

1. Find the quantized file size, which is the weights.
2. Find `layers`, `kv_heads` (or `num_key_value_heads`), `head_dim` in the config, and
   compute bytes per token.
3. Multiply by the context you actually intend to use, not the maximum advertised.
4. Add the embedding model if it must stay resident.
5. Compare against ~7.5 GB, not 8.

If it does not fit, Ollama will still run it by offloading layers to CPU, which is much
slower but works. vLLM would refuse to start, which is one of the reasons it was deferred.
