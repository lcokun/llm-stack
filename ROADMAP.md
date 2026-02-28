# Local LLM Stack — Roadmap

## System
- GPU: NVIDIA RTX 5000 Ada (32GB VRAM)
- CPU: i9-14900K | RAM: 128GB
- Tailscale: active (5 devices)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                     Docker Network                        │
│                                                           │
│  ┌──────────┐   ┌────────────┐   ┌───────────────────┐  │
│  │  Ollama   │   │ Perplexica │   │  Vision Bridge    │  │
│  │ (models)  │◄──│ (search)   │   │  (proxy :11435)   │  │
│  │ :11434    │   │ :3000      │   │                   │  │
│  └────┬─────┘   └─────┬──────┘   └────────┬──────────┘  │
│       │               │                    │             │
│       │          ┌────┴─────┐              │             │
│       │◄─────────│ SearXNG  │     oterm ───┘             │
│       │          │ :4000    │     (TUI client,           │
│       │          └──────────┘      talks to proxy)       │
│       │                                                   │
│  ┌────┴──────────────────────────────────────────────┐   │
│  │           NVIDIA Container Toolkit                 │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
         ▲
         │ Tailscale SSH / port forwarding
         │
    ┌────┴─────┐
    │  Remote  │
    │ Machines │
    └──────────┘
```

### How tandem models work (Vision Bridge)

oterm only supports one model per session. The **Vision Bridge** is a lightweight
proxy (~100-150 lines of Python) that speaks the Ollama API and sits between
oterm and Ollama:

```
oterm ──► Vision Bridge (:11435) ──► detects image in message
                                          │
                                     ┌────┴────┐
                                     │ vision   │ → "This image shows..."
                                     │ model    │
                                     └────┬────┘
                                          │ inject description into prompt
                                     ┌────┴────────┐
                                     │ abliterated  │ → final response
                                     │ model        │
                                     └──────────────┘
```

When no image is present, requests pass straight through to the abliterated model.
When an image is detected, it first gets described by the vision model, then that
description is prepended to the conversation for the abliterated model to use.

## TUI & Web Interfaces

- **oterm**: TUI for direct LLM chat (supports images, pointed at Vision Bridge)
- **Perplexica**: web UI for search-augmented chat (no TUI exists — it
  orchestrates search + LLM in a pipeline that has no CLI equivalent)
- Both accessible from any machine via Tailscale

---

## Phase 1: Foundation — Docker + GPU Passthrough
**Goal**: Get Docker running with GPU access.

### Steps
1. Install Docker Engine (not Docker Desktop)
2. Install NVIDIA Container Toolkit
3. Verify GPU passthrough: `docker run --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`

### What you'll learn
- Docker basics: images, containers, volumes, networks
- How GPU passthrough works in containers (nvidia-container-runtime)

---

## Phase 2: Ollama + oterm — Model Server & TUI
**Goal**: Run Ollama in Docker, pull models, chat via oterm.

### Steps
1. Run Ollama container with GPU access and persistent volume
2. Pull an abliterated model (e.g., `mannix/llama3.1-8b-abliterated`)
3. Pull a vision model (e.g., `llama3.2-vision:11b`)
4. Install oterm (`pip install oterm` or via pipx)
5. Test direct chat: point oterm at Ollama, talk to each model
6. Verify the API works: `curl http://localhost:11434/api/chat`

### Models to consider (fit in 32GB VRAM)
| Model | Type | Size | Notes |
|-------|------|------|-------|
| `mannix/llama3.1-8b-abliterated` | Abliterated | ~5GB | Good balance |
| `llama3.2-vision:11b` | Vision | ~7GB | Native multimodal |
| `dolphin-llama3:8b` | Uncensored | ~5GB | Alternative abliterated |
| `minicpm-v` | Vision | ~5GB | Lighter vision option |

### What you'll learn
- Ollama's architecture (model management, API, Modelfile)
- Quantization levels (Q4, Q5, Q8) and VRAM tradeoffs
- How multimodal models handle image input
- oterm configuration and usage

---

## Phase 3: Vision Bridge — Tandem Model Proxy
**Goal**: Build the proxy that chains vision + abliterated models together.

### Steps
1. Write a Python proxy (FastAPI or aiohttp) that implements the Ollama
   `/api/chat` endpoint
2. Add image detection: if message contains base64 image data, route to
   vision model first
3. Inject the vision model's description into the abliterated model's context
4. Pass through all non-image requests directly to the abliterated model
5. Also proxy `/api/tags` and `/api/show` so oterm sees available models
6. Containerize the proxy (Dockerfile)
7. Point oterm at the proxy: `OLLAMA_URL=http://localhost:11435`
8. Test: send an image in oterm, verify it gets described then discussed

### What you'll learn
- How the Ollama API works under the hood
- Streaming response proxying
- Building a lightweight API middleware
- How multimodal models encode/decode images

---

## Phase 4: Perplexica + SearXNG — Real-Time Search
**Goal**: Add internet search capability so your LLM isn't limited to training data.

### Steps
1. Clone Perplexica repo
2. Configure `config.toml` to point at your Ollama instance
3. Deploy SearXNG (Perplexica's search backend) via Docker
4. Deploy Perplexica via Docker Compose
5. Test a search-augmented query

### What you'll learn
- How search-augmented generation works (different from RAG)
- SearXNG as a meta-search engine
- Docker Compose for multi-container orchestration

---

## Phase 5: Docker Compose — Unify Everything
**Goal**: Single `docker compose up` to bring up the entire stack.

### Steps
1. Write a `docker-compose.yml` that includes:
   - Ollama (with GPU)
   - Vision Bridge proxy
   - SearXNG
   - Perplexica
2. Set up shared Docker network so containers can talk
3. Add persistent volumes for models and configs
4. Add healthchecks and restart policies
5. Test full stack: `docker compose up -d`
6. Install oterm on host, point at Vision Bridge container

### What you'll learn
- Docker Compose: services, networks, volumes, depends_on
- Container networking (DNS resolution between services)
- Managing a multi-container application

---

## Phase 6: Tailscale Access — Use From Any Machine
**Goal**: Access your LLM stack from all your Tailscale devices.

### Steps
1. Verify Tailscale is serving on this machine
2. Option A: SSH into this machine, run oterm directly (best TUI experience)
3. Option B: Use `tailscale serve` to expose Perplexica web UI
4. Option C: Access Ollama/proxy API directly via `http://<tailscale-ip>:<port>`
5. Test from another machine on your tailnet
6. (Optional) Set up `tailscale funnel` if you want HTTPS access

### What you'll learn
- Tailscale networking (MagicDNS, serve, funnel)
- Securing services on a private network vs exposing publicly

---

## Phase 7 (Future): RAG Pipeline
**Goal**: Add document ingestion and retrieval-augmented generation.

### Steps (when ready)
1. Add a vector database (ChromaDB or Qdrant) to docker-compose
2. Add an embedding model to Ollama (e.g., `nomic-embed-text`)
3. Build an ingestion pipeline (parse docs → chunk → embed → store)
4. Integrate retrieval into the Vision Bridge proxy or build separate service
5. Test retrieval quality and tune chunking strategy

### What you'll learn
- Vector databases and similarity search
- Embedding models vs generative models
- Chunking strategies and their impact on retrieval quality

---

## Suggested Order
```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
  │                        │                                     │
  │              tandem models working                           │
  └──── basic LLM chat after Phase 2 ───────────────────────────┘
                                                                 │
                                                           Phase 7 (later)
```

Start with Phase 1 when you're ready. Tell me which phase to begin.
