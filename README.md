# Clyde

Clyde is an AI Agent.

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
Clyde is an AI Agent

## Runtime configuration
Both `main.py` and `main-cyberpunk.py` now read startup settings from environment variables:

- `FLASK_DEBUG` (default: `0`)
- `HOST` (default: `127.0.0.1`)
- `PORT` (default: `5000`)

### Safe defaults
- **Local development**: keep `HOST=127.0.0.1` and set `FLASK_DEBUG=1` when you need the Flask debugger/reloader.
- **Deployment**: keep `FLASK_DEBUG=0`, bind to the required interface with `HOST` (often `0.0.0.0` in containers), and set `PORT` from your runtime environment.

Example:

```bash
FLASK_DEBUG=1 HOST=127.0.0.1 PORT=5000 python main.py
```

