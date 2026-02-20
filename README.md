# Clyde

Clyde is an AI Agent backed by Ollama.

## Required environment variables

Both entrypoints (`main.py` and `main-cyberpunk.py`) require these environment variables:

- `OLLAMA_API_BASE`: Base URL for the Ollama API (for example `http://localhost:11434`).
- `OLLAMA_MODEL`: Ollama model name to use (for example `qwen3:4b-16k`).

### Local development defaults

When `APP_ENV` or `FLASK_ENV` is set to `local`, `dev`, or `development`, the app will use local defaults if either value is unset:

- `OLLAMA_API_BASE=http://localhost:11434`
- `OLLAMA_MODEL=qwen3:4b-16k` (`main.py`) or `gpt-oss:120b-cloud` (`main-cyberpunk.py`)

Outside local development, missing or invalid values cause startup to fail with clear error logs.

## Example launch commands

### Standard UI (`main.py`)

```bash
OLLAMA_API_BASE=http://localhost:11434 \
OLLAMA_MODEL=qwen3:4b-16k \
python main.py
```

### Cyberpunk UI (`main-cyberpunk.py`)

```bash
OLLAMA_API_BASE=http://localhost:11434 \
OLLAMA_MODEL=gpt-oss:120b-cloud \
python main-cyberpunk.py
```

### Local development with fallback defaults

```bash
APP_ENV=development python main.py
```

```bash
FLASK_ENV=dev python main-cyberpunk.py
```
