# LLM Stack

A self-hosted LLM stack running in Docker with GPU acceleration. Chains an abliterated (uncensored) model with a vision model and web search through a transparent proxy.

## Architecture

```
oterm --> Vision Bridge (:11435) --> Ollama (:11434)
               |         |    |          |
               |         |    |          +-- runs models on GPU
               |         |    |
               |         |    +-- /rag prefix? --> ChromaDB --> inject docs
               |         |
               |         +-- /search prefix? --> SearXNG --> inject results
               |
               +-- image detected? --> vision model --> inject description
               |
               +-- otherwise --> pass through to chat model
```

**Ollama** -- model server with NVIDIA GPU passthrough
**Vision Bridge** -- Python proxy that detects images, search queries, and RAG lookups
**SearXNG** -- private, self-hosted metasearch engine
**ChromaDB** -- vector database for document storage and retrieval
**oterm** -- terminal UI client for chatting

## Quick Start

### Prerequisites

- NVIDIA GPU with sufficient VRAM (tested on RTX 5000 Ada 32GB)
- [Docker Engine](https://docs.docker.com/engine/install/) + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- Python 3.10+ (for oterm)

Verify GPU access in Docker:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### Start the stack

```bash
git clone https://github.com/lcokun/llm-stack.git
cd llm-stack
docker compose up --build -d
```

### Pull models

```bash
docker exec ollama ollama pull mannix/llama3.1-8b-abliterated
docker exec ollama ollama pull llama3.2-vision:11b
```

### Install oterm and chat

```bash
pipx install oterm
```

Regular chat (direct to Ollama):
```bash
oterm
```

Vision + search enabled chat (through the bridge):
```bash
OLLAMA_HOST=127.0.0.1:11435 oterm
```

## Features

### Vision chaining

Send an image with your message. The bridge:
1. Detects the image in the request
2. Sends it to the vision model for a description
3. Strips the image and prepends `[Image description: ...]` to your message
4. Forwards the enriched text to the abliterated model

The abliterated model never sees the image directly -- it gets a text description plus your question.

### Web search

Prefix any message with `/search` to trigger a web search:
```
/search latest news about local LLMs
```

The bridge queries SearXNG, injects the top 5 results into context, and forwards everything to the chat model.

### RAG (document Q&A)

Ingest a file into ChromaDB:
```
/ingest /data/Documents/report.pdf
```

Then ask questions about your ingested documents:
```
/rag what did the report say about budgets?
```

The bridge embeds your query, finds the most relevant chunks from ChromaDB, and injects them as context.

Supported file types: PDF, DOCX, XLSX, PPTX, CSV, TXT, Markdown.

**Note:** `/ingest` can only read files on the workstation (mounted at `/data`). To ingest files from a remote machine, copy them to the workstation first.

## Swapping Models

Pull your preferred models and update `docker-compose.yml`:

```bash
docker exec ollama ollama pull <your-chat-model>
docker exec ollama ollama pull <your-vision-model>
```

```yaml
environment:
  - CHAT_MODEL=<your-chat-model>
  - VISION_MODEL=<your-vision-model>
```

```bash
docker compose up -d vision-bridge
```

Browse available models at [ollama.com/library](https://ollama.com/library).

## Services

| Service | Port | Description |
|---------|------|-------------|
| Ollama | 11434 | Model server API |
| Vision Bridge | 11435 | Proxy API (vision + search + RAG) |
| SearXNG | internal | Metasearch engine (not exposed) |
| ChromaDB | internal | Vector database (not exposed) |

## Default Models

| Model | Purpose | Size |
|-------|---------|------|
| `mannix/llama3.1-8b-abliterated` | Main chat (uncensored) | ~5 GB |
| `llama3.2-vision:11b` | Image understanding | ~8 GB |
| `nomic-embed-text` | Document embeddings (RAG) | ~274 MB |

## Roadmap

- [x] Docker + GPU passthrough
- [x] Ollama + oterm
- [x] Vision Bridge proxy
- [x] SearXNG search integration
- [x] Unified Docker Compose
- [x] Tailscale access
- [x] RAG pipeline (partial -- ingestion limited to workstation files)
