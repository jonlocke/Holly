from flask import Flask, render_template, request, Response
from ollama import Client
import json
import logging
import os
from urllib.parse import urlparse

app = Flask(__name__)

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_OLLAMA_API_BASE = "http://localhost:11434"
DEFAULT_LOCAL_OLLAMA_MODEL = "qwen3:4b-16k"


def is_local_development() -> bool:
    env = os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or ""
    return env.lower() in {"dev", "development", "local"}


def _validate_ollama_api_base(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def load_ollama_config() -> tuple[str, str]:
    api_base = os.environ.get("OLLAMA_API_BASE", "").strip()
    model = os.environ.get("OLLAMA_MODEL", "").strip()

    if is_local_development():
        if not api_base:
            api_base = DEFAULT_LOCAL_OLLAMA_API_BASE
            logger.warning(
                "OLLAMA_API_BASE is missing; defaulting to local development value '%s'.",
                api_base,
            )
        if not model:
            model = DEFAULT_LOCAL_OLLAMA_MODEL
            logger.warning(
                "OLLAMA_MODEL is missing; defaulting to local development value '%s'.",
                model,
            )

    errors = []
    if not api_base:
        errors.append(
            "OLLAMA_API_BASE is required. Set it to your Ollama host URL (e.g. http://localhost:11434)."
        )
    elif not _validate_ollama_api_base(api_base):
        errors.append(
            f"OLLAMA_API_BASE '{api_base}' is invalid. Use a full URL such as http://localhost:11434."
        )

    if not model:
        errors.append(
            "OLLAMA_MODEL is required. Set it to an available model name (e.g. qwen3:4b-16k)."
        )

    if errors:
        for error in errors:
            logger.error(error)
        raise RuntimeError("Invalid Ollama configuration. See startup errors above.")

    logger.info("Using OLLAMA_API_BASE=%s and OLLAMA_MODEL=%s", api_base, model)
    return api_base, model


OLLAMA_API_BASE, OLLAMA_MODEL = load_ollama_config()
client = Client(host=OLLAMA_API_BASE)


@app.route("/")
def index():
    return render_template("index.html")


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/stream")
def stream():
    user_message = request.args.get("message")

    def generate():
        try:
            stream = client.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": user_message}],
                stream=True,
            )

            for chunk in stream:
                if "message" in chunk:
                    content = chunk["message"].get("content", "")
                    if content:
                        yield sse({"type": "token", "content": content})

            yield sse({"type": "done"})

        except Exception as e:
            yield sse({"type": "error", "error": str(e)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, threaded=True, host=host, port=port)
