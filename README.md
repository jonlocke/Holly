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
- `OPENCLAW_AGENT_MODEL` (default: `agent:holly`; used as the chat `model` when bearer-token/OpenAI-compatible mode is enabled)
- `OPENCLAW_AGENT_ID` (default: `holly`; sent as `X-OpenClaw-Agent-Id` in bearer-token/OpenAI-compatible mode to force routing to that agent)

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
sudo dpkg -i dist/clyde-ux_*.deb
```

The package installs:

- application files in `/opt/clyde-ux`
- service unit in `/lib/systemd/system/clyde-ux.service`
- runtime env defaults in `/etc/default/clyde-ux`

Manage the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clyde-ux.service
sudo systemctl status clyde-ux.service
sudo systemctl restart clyde-ux.service
sudo systemctl stop clyde-ux.service
```

After install, adjust runtime variables in `/etc/default/clyde-ux` (notably `OLLAMA_API_BASE` and `OLLAMA_MODEL`) and restart the service.
