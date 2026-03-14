# Holly

Holly is an AI Agent.

## Minimal setup (virtualenv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Or run the helper script:

```bash
./dep.sh
source .venv/bin/activate
```

## Optional lockfile workflow (deterministic installs)

If you want deterministic installs across machines, generate a lockfile from pinned dependencies:

```bash
pip install pip-tools
pip-compile --generate-hashes -o requirements.lock requirements.txt
pip install --require-hashes -r requirements.lock
```

Commit `requirements.lock` whenever dependencies change.
Holly is an AI Agent

## Runtime configuration
Both `main.py` and `main-cyberpunk.py` now read startup settings from environment variables:

- `FLASK_DEBUG` (default: `0`)
- `HOST` (default: `127.0.0.1`)
- `PORT` (default: `5000`)
- `OLLAMA_EMBED_MODEL` (default: `nomic-embed-text` for RAG embedding in `main.py`)
- `OLLAMA_BEARER_TOKEN` (optional bearer token for Ollama/OpenAI-compatible endpoints that require `Authorization: Bearer ...`)
- `OPENCLAW_AGENT_MODEL` (optional override; defaults to `OLLAMA_MODEL` and is used as the chat `model` when bearer-token/OpenAI-compatible mode is enabled)
- `OPENCLAW_AGENT_ID` (default: `holly`; sent as `X-OpenClaw-Agent-Id` in bearer-token/OpenAI-compatible mode to force routing to that agent)
- `OPENCLAW_SESSION_HEADER` (default: `X-OpenClaw-Session-Id`; sent with the Flask session id so OpenClaw can reuse one agent session across UX messages)
- `CHAT_REQUEST_TIMEOUT_SECONDS` (optional; minimum/default: `120`; total timeout for chat generation requests to backend LLM endpoints)
- `TTS_MODE` (optional; set `qwen3` to enable Qwen3 health-check + `/speak` behavior)
- `QWEN_TTS_API_BASE` (optional; when set, enables a `/text-to-speech` proxy endpoint)
- `QWEN_TTS_ENDPOINT_STYLE` (optional; default: `quick` → upstream path `/speak`; also supports `openai` → `/v1/audio/speech`, `legacy` → `/text-to-speech`; primarily used outside `TTS_MODE=qwen3`)
- `QWEN_TTS_ENDPOINT` (optional; overrides endpoint style with an explicit upstream path; primarily used outside `TTS_MODE=qwen3`)
- `TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS` (optional; default: `20`; strict total deadline for `/text-to-speech` upstream connect + response read before browser fallback is returned)
- `WHISPER_CPP_STT_ENDPOINT` (optional; default: `http://127.0.0.1:9000/inference`; enables `/speech-to-text` proxy routing to whisper.cpp)
- `STT_UPSTREAM_TOTAL_TIMEOUT_SECONDS` (optional; default: `60`; strict total deadline for `/speech-to-text` upstream connect + response read)
- `STT_UPSTREAM_FILE_FIELD` (optional; default: `file`; multipart form field name used when forwarding audio to the STT backend)

### RAG embedding model

RAG ingestion/retrieval in `main.py` is configured to use `OLLAMA_EMBED_MODEL`, defaulting to `nomic-embed-text` so it can be used without extra setup in local development.

If needed, pull the model first:

```bash
ollama pull nomic-embed-text
```


### Chat commands

- `/help`: shows the available slash commands.
- `/models`: lists currently available models from the configured backend.
- `/clear`: clears the current session knowledge base.
- `/git <repository-url>`: clones a Git repository (for example `git@github.com:jonlocke/AImaster-linux.git`) and indexes repository text content into session RAG context.
- `/vectordb`: shows in-memory vector store size (total indexed chunks) and open sessions with indexed chunk counts.

### Safe defaults
- **Local development**: keep `HOST=127.0.0.1` and set `FLASK_DEBUG=1` when you need the Flask debugger/reloader.
- **Deployment**: keep `FLASK_DEBUG=0`, bind to the required interface with `HOST` (often `0.0.0.0` in containers), and set `PORT` from your runtime environment.

Example:

```bash
FLASK_DEBUG=1 HOST=127.0.0.1 PORT=5000 python main.py
```

With bearer token auth (OpenClaw gateway / OpenAI-compatible endpoint):

```bash
OLLAMA_API_BASE=http://127.0.0.1:18789 \
OLLAMA_BEARER_TOKEN=your_gateway_token \
python main.py
```

Notes:
- The app will call `POST /v1/chat/completions` when `OLLAMA_BEARER_TOKEN` is set.
- `OLLAMA_API_BASE` can be either the gateway root (`http://127.0.0.1:18789`) or `/v1` base (`http://127.0.0.1:18789/v1`).
- When `QWEN_TTS_API_BASE` is set, Holly exposes `POST /text-to-speech` and forwards JSON payloads to the configured Qwen TTS backend.
  - In `TTS_MODE=qwen3`, Holly first checks `<QWEN_TTS_API_BASE>/health`.
  - If `/health` is available, Holly sends TTS to `<QWEN_TTS_API_BASE>/speak`.
  - If `/health` is unavailable/fails, Holly returns JSON fallback for browser speech: `{ "fallback": "browser_speak", "text": ... }`.
  - Outside `TTS_MODE=qwen3`, routing follows `QWEN_TTS_ENDPOINT` / `QWEN_TTS_ENDPOINT_STYLE`.
- Holly exposes `POST /speech-to-text`, receives microphone audio from the browser, and forwards multipart form-data (`file`) to `WHISPER_CPP_STT_ENDPOINT` (for example a local whisper.cpp server).

### TTS troubleshooting

Recommended env for Qwen3 with health-check + `/speak` routing:

```bash
TTS_MODE=qwen3
QWEN_TTS_API_BASE=http://192.168.1.154:8765
```

How to validate quickly:

```bash
curl -i http://192.168.1.154:8765/health
curl -i -X POST http://127.0.0.1:5000/text-to-speech \
  -H "Content-Type: application/json" \
  -d '{"text":"TTS test from Holly"}'
```

Expected behavior:
- If `/health` returns success, Holly sends TTS upstream to `/speak`.
- If `/health` fails or is unreachable, Holly returns browser fallback JSON (`fallback: browser_speak`).
- If you are not using `TTS_MODE=qwen3`, set `QWEN_TTS_ENDPOINT` or `QWEN_TTS_ENDPOINT_STYLE` for your provider route.

## Debian 13 package + systemd service

Build a Debian package (tested flow for Debian 13/bookworm-trixie style tooling):

```bash
./scripts/package-deb.sh
```

Optional build variables:

- `VERSION=1.2.3 ./scripts/package-deb.sh`
- `OUT_DIR=./dist ./scripts/package-deb.sh`
- `ARCH=amd64 ./scripts/package-deb.sh`
- `SKIP_PIP_INSTALL=1 ./scripts/package-deb.sh` (offline packaging validation only)

Install the generated package:

```bash
sudo dpkg -i dist/holly-ux_*.deb
```

The package installs:

- application files in `/opt/holly-ux`
- service unit in `/lib/systemd/system/holly-ux.service`
- runtime env defaults in `/etc/default/holly-ux`

Manage the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now holly-ux.service
sudo systemctl status holly-ux.service
sudo systemctl restart holly-ux.service
sudo systemctl stop holly-ux.service
```

After install, adjust runtime variables in `/etc/default/holly-ux` (notably `OLLAMA_API_BASE` and `OLLAMA_MODEL`) and restart the service.
