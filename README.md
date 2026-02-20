# Clyde
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

