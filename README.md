# Local LLM Stack

A self-hosted LLM stack running in Docker with GPU acceleration. Features an abliterated (uncensored) model, a vision model, and a transparent proxy that chains them together.

## Architecture

```
oterm ──► Vision Bridge (:11435) ──► Ollama (:11434)
              │                          │
              │ detects image?           │ runs models on GPU
              │   yes → vision model     │
              │   no  → pass through     │
              └──────────────────────────┘
```

- **Ollama** - model server with GPU passthrough (NVIDIA)
- **Vision Bridge** - lightweight Python proxy (~130 lines) that detects images in chat, calls the vision model for a description, then injects it into the abliterated model's context
- **oterm** - terminal UI client for chatting

## Requirements

- NVIDIA GPU with sufficient VRAM (tested on RTX 5000 Ada 32GB)
- Docker Engine + NVIDIA Container Toolkit
- Python 3.10+ (for oterm)

## Setup

### 1. Install Docker Engine

**Ubuntu:**
```bash
sudo apt update
sudo apt install docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

**Arch:**
```bash
sudo pacman -S docker docker-compose
# or: yay -S docker docker-compose
# or: paru -S docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# Log out and back in for group change to take effect
```

### 2. Install NVIDIA Container Toolkit

**Ubuntu:**
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

**Arch:**
```bash
sudo pacman -S nvidia-container-toolkit
# or: yay -S nvidia-container-toolkit
# or: paru -S nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify GPU access:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### 3. Clone and start the stack

```bash
git clone https://github.com/lcokun/local-llm.git
cd local-llm
docker compose up --build -d
```

### 4. Pull the models

```bash
docker exec ollama ollama pull mannix/llama3.1-8b-abliterated
docker exec ollama ollama pull llama3.2-vision:11b
```

### 5. Install oterm

```bash
pipx install oterm
```

### 6. Chat

Regular chat (direct to Ollama):
```bash
oterm
```

Vision-enabled chat (through the bridge):
```bash
OLLAMA_HOST=127.0.0.1:11435 oterm
```

## How Vision Bridge Works

When you send a message **without an image**, it passes straight through to the abliterated model.

When you send a message **with an image**:
1. The bridge detects the image in the request
2. Sends it to the vision model (`llama3.2-vision:11b`) for a description
3. Strips the image and prepends `[Image description: ...]` to your message
4. Forwards the modified message to the abliterated model (`mannix/llama3.1-8b-abliterated`)

The abliterated model never sees the image directly. It just gets a text description plus your question, letting you use an uncensored model for reasoning while leveraging a vision model for image understanding.

## Using Different Models

You can swap in any Ollama-compatible models. Two places to change:

**1. Pull your models:**
```bash
docker exec ollama ollama pull <your-chat-model>
docker exec ollama ollama pull <your-vision-model>
```

**2. Update `docker-compose.yml` environment variables:**
```yaml
environment:
  - CHAT_MODEL=<your-chat-model>
  - VISION_MODEL=<your-vision-model>
```

Then restart the bridge:
```bash
docker compose up -d vision-bridge
```

Browse available models at [ollama.com/library](https://ollama.com/library).

## Models

| Model | Type | Size | Purpose |
|-------|------|------|---------|
| `mannix/llama3.1-8b-abliterated` | Abliterated | ~5 GB | Main chat model (uncensored) |
| `llama3.2-vision:11b` | Vision | ~8 GB | Image description |

## Ports

| Service | Port | Description |
|---------|------|-------------|
| Ollama | 11434 | Model server API |
| Vision Bridge | 11435 | Proxy API (use this for vision-enabled chat) |

## Roadmap

- [x] Docker + GPU passthrough
- [x] Ollama + oterm (model serving + TUI client)
- [x] Vision Bridge proxy (tandem model chaining)
- [ ] Perplexica + SearXNG (search-augmented generation)
- [ ] Unified Docker Compose (all services in one stack)
- [ ] Tailscale access (use from any device)
- [ ] RAG pipeline (document ingestion + retrieval)
