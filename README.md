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
