from flask import Flask, render_template, request, Response, jsonify, session
from ollama import Client
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import subprocess  # nosec B404 - subprocess is required for git clone; calls are constrained and validated.
import tempfile
import threading
import time
import ipaddress
import re
import socket
import queue
from urllib.parse import urlparse
from urllib import request as urllib_request
from urllib import error as urllib_error

from math import sqrt

app = Flask(__name__)
_configured_secret = os.environ.get("FLASK_SECRET_KEY", "").strip()
app.secret_key = _configured_secret or secrets.token_hex(32)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

if not _configured_secret:
    logger.warning(
        "FLASK_SECRET_KEY is not set; using a random in-memory secret. "
        "If you run multiple workers or restart often, Flask sessions will rotate and appear as new sessions."
    )

DEFAULT_LOCAL_OLLAMA_API_BASE = "http://localhost:11434"
DEFAULT_LOCAL_OLLAMA_MODEL = "qwen3:4b-16k"
DEFAULT_LOCAL_OLLAMA_EMBED_MODEL = "nomic-embed-text"
ALLOWED_OUTBOUND_SCHEMES = {"http", "https"}
ALLOWED_GIT_URL_SCHEMES = {"http", "https"}
HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}$)(?!-)[a-zA-Z0-9.-]+(?<!-)$")
GIT_EXECUTABLE = shutil.which("git")


def is_local_development() -> bool:
    env = os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV") or ""
    return env.lower() in {"dev", "development", "local"}


if not is_local_development():
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )


def _validate_ollama_api_base(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_valid_hostname(hostname: str) -> bool:
    if not hostname:
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return bool(HOSTNAME_PATTERN.fullmatch(hostname))


def _validate_outbound_http_url(url: str) -> str:
    target = (url or "").strip()
    if not target:
        raise ValueError("Outbound URL is empty.")

    parsed = urlparse(target)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_OUTBOUND_SCHEMES:
        raise ValueError(f"Outbound URL scheme '{parsed.scheme}' is not allowed.")

    hostname = parsed.hostname
    if not _is_valid_hostname(hostname or ""):
        raise ValueError(f"Outbound URL host '{hostname}' is invalid.")

    if parsed.username or parsed.password:
        raise ValueError("Outbound URL userinfo is not allowed.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"Outbound URL port is invalid: {exc}") from exc

    return target


def _resolve_hostname_ips(hostname: str) -> list[ipaddress._BaseAddress]:
    resolved: list[ipaddress._BaseAddress] = []
    for _, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        try:
            resolved.append(ipaddress.ip_address(ip_str))
        except ValueError:
            continue
    return resolved


def _is_blocked_network_address(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_git_repo_url(repo_url: str) -> str:
    target = (repo_url or "").strip()
    if not target:
        raise ValueError("Repository URL is empty.")

    parsed = urlparse(target)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_GIT_URL_SCHEMES:
        raise ValueError(
            f"Unsupported repository URL scheme '{parsed.scheme}'. "
            "Use one of: http, https."
        )

    if not _is_valid_hostname(parsed.hostname or ""):
        raise ValueError("Repository URL host is invalid.")

    if parsed.username or parsed.password:
        raise ValueError("Repository URL must not include embedded credentials.")

    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"Repository URL port is invalid: {exc}") from exc

    try:
        resolved_ips = _resolve_hostname_ips(parsed.hostname or "")
    except socket.gaierror as exc:
        raise RuntimeError(f"Unable to resolve repository hostname '{parsed.hostname}'.") from exc

    if not resolved_ips:
        raise RuntimeError(f"Unable to resolve repository hostname '{parsed.hostname}'.")

    for ip in resolved_ips:
        if _is_blocked_network_address(ip):
            raise ValueError(f"Repository URL resolves to blocked network address: {ip}")

    return target


def load_ollama_config() -> tuple[str, str, str]:
    api_base = os.environ.get("OLLAMA_API_BASE", "").strip()
    model = os.environ.get("OLLAMA_MODEL", "").strip()
    embed_model = os.environ.get("OLLAMA_EMBED_MODEL", "").strip()

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
        if not embed_model:
            embed_model = DEFAULT_LOCAL_OLLAMA_EMBED_MODEL
            logger.warning(
                "OLLAMA_EMBED_MODEL is missing; defaulting to local development value '%s'.",
                embed_model,
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

    if not embed_model:
        embed_model = DEFAULT_LOCAL_OLLAMA_EMBED_MODEL
        logger.info(
            "OLLAMA_EMBED_MODEL is missing; defaulting to '%s' for retrieval.",
            embed_model,
        )

    if errors:
        for error in errors:
            logger.error(error)
        raise RuntimeError("Invalid Ollama configuration. See startup errors above.")

    logger.info(
        "Using OLLAMA_API_BASE=%s, OLLAMA_MODEL=%s, and OLLAMA_EMBED_MODEL=%s",
        api_base,
        model,
        embed_model,
    )
    return api_base, model, embed_model


OLLAMA_API_BASE, OLLAMA_MODEL, OLLAMA_EMBED_MODEL = load_ollama_config()
OLLAMA_BEARER_TOKEN = os.environ.get("OLLAMA_BEARER_TOKEN", "").strip()

_client_options = {"host": OLLAMA_API_BASE}
if OLLAMA_BEARER_TOKEN:
    _client_options["headers"] = {
        "Authorization": f"Bearer {OLLAMA_BEARER_TOKEN}",
    }
    logger.info("Using bearer token authentication for Ollama API requests.")

client = Client(**_client_options)


def _openai_chat_completions_url() -> str:
    base = OLLAMA_API_BASE.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


OPENCLAW_AGENT_MODEL = os.environ.get("OPENCLAW_AGENT_MODEL", "agent:holly").strip() or "agent:holly"
OPENCLAW_AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "holly").strip() or "holly"
OPENCLAW_SESSION_HEADER = (
    os.environ.get("OPENCLAW_SESSION_HEADER", "x-openclaw-session-key").strip()
    or "x-openclaw-session-key"
)


def _resolve_qwen_tts_endpoint_path() -> str:
    explicit = os.environ.get("QWEN_TTS_ENDPOINT", "").strip()
    if explicit:
        return explicit if explicit.startswith("/") else f"/{explicit}"

    style = os.environ.get("QWEN_TTS_ENDPOINT_STYLE", "quick").strip().lower()
    if style == "openai":
        return "/v1/audio/speech"
    if style in {"legacy", "text-to-speech", "text_to_speech"}:
        return "/text-to-speech"
    # quick/default: direct speak endpoint
    return "/speak"


def _resolve_qwen_tts_url() -> str | None:
    base = os.environ.get("QWEN_TTS_API_BASE", "").strip().rstrip("/")
    if not base:
        return None
    endpoint_path = _resolve_qwen_tts_endpoint_path()
    return f"{base}{endpoint_path}"


def _resolve_qwen_tts_health_url() -> str | None:
    base = os.environ.get("QWEN_TTS_API_BASE", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/health"


def _resolve_qwen3_tts_speak_url() -> str | None:
    base = os.environ.get("QWEN_TTS_API_BASE", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/speak"


def _load_tts_upstream_total_timeout_seconds() -> float:
    default_timeout = 20.0
    raw = os.environ.get("TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS", str(default_timeout)).strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS=%r; using %.1fs default.",
            raw,
            default_timeout,
        )
        return default_timeout

    if value <= 0:
        logger.warning(
            "Non-positive TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS=%r; using %.1fs default.",
            raw,
            default_timeout,
        )
        return default_timeout
    return value


TTS_MODE = os.environ.get("TTS_MODE", "").strip().lower()
QWEN_TTS_URL = _resolve_qwen_tts_url()
QWEN_TTS_HEALTH_URL = _resolve_qwen_tts_health_url()
QWEN3_TTS_SPEAK_URL = _resolve_qwen3_tts_speak_url()
TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS = _load_tts_upstream_total_timeout_seconds()
FRONTEND_TTS_AUTOPLAY = os.environ.get("FRONTEND_TTS_AUTOPLAY", "0").strip().lower() in {"1", "true", "yes", "on"}
if QWEN_TTS_URL:
    logger.info("QWEN TTS proxy enabled: %s", QWEN_TTS_URL)


def _list_available_models() -> list[str]:
    if OLLAMA_BEARER_TOKEN:
        base = OLLAMA_API_BASE.rstrip("/")
        candidate_endpoints = [
            f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models",
            f"{base}/models",
        ]

        last_error: Exception | None = None
        for endpoint in candidate_endpoints:
            safe_endpoint = _validate_outbound_http_url(endpoint)
            req = urllib_request.Request(
                safe_endpoint,
                method="GET",
                headers={"Authorization": f"Bearer {OLLAMA_BEARER_TOKEN}"},
            )

            try:
                with urllib_request.urlopen(req, timeout=30) as response:  # nosec B310 - URL is validated by _validate_outbound_http_url.
                    payload = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
            except Exception as exc:
                last_error = exc
                continue

            models = []
            for item in payload.get("data", []):
                model_id = item.get("id")
                if isinstance(model_id, str) and model_id.strip():
                    models.append(model_id.strip())

            return sorted(set(models))

        if last_error:
            raise RuntimeError(f"model listing failed: {last_error}") from last_error
        return []

    try:
        listing = client.list()
    except Exception:
        listing = {"models": []}

    models = []
    for item in listing.get("models", []):
        if isinstance(item, dict):
            name = item.get("model") or item.get("name")
            if isinstance(name, str) and name.strip():
                models.append(name.strip())

    if models:
        return sorted(set(models))

    # Fallback for older Ollama client/server combinations.
    tags_url = _validate_outbound_http_url(f"{OLLAMA_API_BASE.rstrip('/')}/api/tags")
    req = urllib_request.Request(tags_url, method="GET")
    with urllib_request.urlopen(req, timeout=30) as response:  # nosec B310 - URL is validated by _validate_outbound_http_url.
        payload = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")

    for item in payload.get("models", []):
        if isinstance(item, dict):
            name = item.get("model") or item.get("name")
            if isinstance(name, str) and name.strip():
                models.append(name.strip())

    return sorted(set(models))


def _stream_chat_tokens(prompt: str, session_id: str | None = None):
    if OLLAMA_BEARER_TOKEN:
        endpoint = _validate_outbound_http_url(_openai_chat_completions_url())
        logger.info("Chat request -> POST %s (bearer auth)", endpoint)

        body = json.dumps(
            {
                "model": OPENCLAW_AGENT_MODEL,
                "stream": True,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")

        request_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OLLAMA_BEARER_TOKEN}",
            "X-OpenClaw-Agent-Id": OPENCLAW_AGENT_ID,
        }

        if session_id:
            request_headers[OPENCLAW_SESSION_HEADER] = session_id

        logger.info(
            "OpenClaw chat request session debug: flask_session_id=%s header=%s value=%s",
            _short_session(session_id),
            OPENCLAW_SESSION_HEADER,
            _short_session(request_headers.get(OPENCLAW_SESSION_HEADER)),
        )

        req = urllib_request.Request(
            endpoint,
            data=body,
            method="POST",
            headers=request_headers,
        )

        try:
            with urllib_request.urlopen(req, timeout=120) as response:  # nosec B310 - URL is validated by _validate_outbound_http_url.
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    if not payload:
                        continue
                    chunk = json.loads(payload)
                    for choice in chunk.get("choices", []):
                        content = (choice.get("delta") or {}).get("content")
                        if content:
                            yield content
        except urllib_error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Gateway chat request to {endpoint} failed ({exc.code}): {details or exc.reason}"
            ) from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Unable to reach gateway chat endpoint {endpoint}: {exc}") from exc
        return

    logger.info(
        "Chat request -> Ollama client host=%s model=%s",
        OLLAMA_API_BASE,
        OLLAMA_MODEL,
    )
    stream = client.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        if "message" in chunk:
            content = chunk["message"].get("content", "")
            if content:
                yield content


MAX_MESSAGE_LENGTH = 16000
MAX_STREAM_BODY_BYTES = 64 * 1024
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024
MAX_FILE_TEXT_LENGTH = 100000
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
EMBED_MODEL = OLLAMA_EMBED_MODEL
RAG_RESULTS = 4
MAX_GIT_FILES = 1000
MAX_GIT_FILE_SIZE_BYTES = 512 * 1024
MAX_GIT_TOTAL_TEXT_BYTES = 2 * 1024 * 1024
GIT_ENDPOINT_TOKEN = os.environ.get("GIT_ENDPOINT_TOKEN", "").strip()

HELP_MESSAGE = """Available commands:
- /help: Show available slash commands and what they do.
- /models: List currently available models.
- /clear: Clear uploaded knowledge/context for your current session.
- /vectordb: Show in-memory vector database statistics.
- /git <repository-url>: Clone and index a repository for RAG queries in this session."""

GIT_TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".adoc", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".env", ".xml", ".csv", ".tsv", ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".m", ".mm", ".rb",
    ".php", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".html", ".htm", ".css", ".scss",
    ".sass", ".less", ".vue", ".svelte", ".dockerfile", ".gitignore", ".gitattributes",
    ".lock", ".properties",
}

_vector_store_lock = threading.Lock()
_session_vector_store: dict[str, list[dict]] = {}
_question_history_lock = threading.Lock()
QUESTION_HISTORY_LIMIT = 200
QUESTION_HISTORY_FILE = Path(
    os.environ.get("QUESTION_HISTORY_FILE", Path(__file__).with_name("question_history.json"))
)
_rate_limit_lock = threading.Lock()
_rate_limit_events: dict[str, dict[str, list[float]]] = {
    "stream": {},
    "upload": {},
    "git": {},
}
RATE_LIMIT_STREAM_MAX = int(os.environ.get("RATE_LIMIT_STREAM_MAX", "30"))
RATE_LIMIT_STREAM_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_STREAM_WINDOW_SECONDS", "60"))
RATE_LIMIT_UPLOAD_MAX = int(os.environ.get("RATE_LIMIT_UPLOAD_MAX", "10"))
RATE_LIMIT_UPLOAD_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_UPLOAD_WINDOW_SECONDS", "60"))
RATE_LIMIT_GIT_MAX = int(os.environ.get("RATE_LIMIT_GIT_MAX", "3"))
RATE_LIMIT_GIT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_GIT_WINDOW_SECONDS", "600"))


def _load_question_history() -> dict[str, list[str]]:
    if not QUESTION_HISTORY_FILE.exists():
        return {}

    try:
        with QUESTION_HISTORY_FILE.open("r", encoding="utf-8") as history_file:
            payload = json.load(history_file)
    except (OSError, json.JSONDecodeError):
        logger.warning("Unable to read question history file '%s'.", QUESTION_HISTORY_FILE)
        return {}

    if not isinstance(payload, dict):
        return {}

    history: dict[str, list[str]] = {}
    for session_id, entries in payload.items():
        if not isinstance(session_id, str) or not isinstance(entries, list):
            continue

        valid_entries = [entry for entry in entries if isinstance(entry, str) and entry.strip()]
        if valid_entries:
            history[session_id] = valid_entries[-QUESTION_HISTORY_LIMIT:]

    return history


def _save_question_history(history: dict[str, list[str]]) -> None:
    QUESTION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with QUESTION_HISTORY_FILE.open("w", encoding="utf-8") as history_file:
        json.dump(history, history_file, ensure_ascii=False, indent=2)
    try:
        os.chmod(QUESTION_HISTORY_FILE, 0o600)
    except OSError:
        logger.warning("Unable to set owner-only permissions on '%s'.", QUESTION_HISTORY_FILE)


def _append_question_history(session_id: str, question: str) -> None:
    cleaned_question = question.strip()
    if not cleaned_question:
        return

    with _question_history_lock:
        history = _load_question_history()
        session_history = history.get(session_id, [])

        if session_history and session_history[-1] == cleaned_question:
            return

        session_history.append(cleaned_question)
        history[session_id] = session_history[-QUESTION_HISTORY_LIMIT:]
        _save_question_history(history)


def _get_question_history(session_id: str) -> list[str]:
    with _question_history_lock:
        history = _load_question_history()
        return history.get(session_id, [])


def _client_rate_limit_key() -> str:
    x_forwarded_for = request.headers.get("X-Forwarded-For", "")
    if x_forwarded_for:
        first_ip = x_forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    return request.remote_addr or "unknown"


def _check_rate_limit(scope: str, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
    now = time.time()
    with _rate_limit_lock:
        scope_events = _rate_limit_events.setdefault(scope, {})
        events = [ts for ts in scope_events.get(key, []) if now - ts < window_seconds]

        if len(events) >= max_requests:
            retry_after = max(1, int(window_seconds - (now - events[0])))
            scope_events[key] = events
            return True, retry_after

        events.append(now)
        scope_events[key] = events
        return False, 0


def _extract_git_auth_token() -> str:
    header_token = (request.headers.get("X-Holly-Git-Token") or "").strip()
    if header_token:
        return header_token

    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    return ""


def _vector_store_stats() -> dict:
    with _vector_store_lock:
        sessions = {
            sid: len(docs)
            for sid, docs in _session_vector_store.items()
            if docs
        }

    total_chunks = sum(sessions.values())
    return {
        "total_chunks": total_chunks,
        "open_sessions": len(sessions),
        "session_chunk_counts": sessions,
    }


def _get_session_id() -> str:
    session_id = session.get("session_id")
    if not session_id:
        session_id = secrets.token_hex(16)
        session["session_id"] = session_id
        logger.info("Created new Flask session_id=%s", session_id)
    return session_id


def _short_session(session_id: str | None) -> str:
    if not session_id:
        return "none"
    if len(session_id) <= 8:
        return session_id
    return f"{session_id[:8]}..."


def _masked_session_suffix(session_id: str) -> str:
    suffix = session_id[-4:] if len(session_id) >= 4 else session_id
    return f"***{suffix}"


def _chunk_text(text: str) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    chunks = []
    start = 0
    step = CHUNK_SIZE - CHUNK_OVERLAP

    while start < len(cleaned):
        end = min(start + CHUNK_SIZE, len(cleaned))
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start += step

    return chunks


def _embed_texts(chunks: list[str]) -> list[list[float]]:
    embed = getattr(client, "embed", None)
    if callable(embed):
        response = embed(model=EMBED_MODEL, input=chunks)
        return response["embeddings"]

    vectors = []
    for chunk in chunks:
        response = client.embeddings(model=EMBED_MODEL, prompt=chunk)
        vectors.append(response["embedding"])
    return vectors


def _is_embedding_not_supported_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "support embeddings" in message or "does not support embeddings" in message


def _keyword_overlap_score(query: str, text: str) -> int:
    query_terms = set(query.lower().split())
    if not query_terms:
        return 0
    text_terms = set(text.lower().split())
    return len(query_terms & text_terms)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sqrt(sum(x * x for x in a))
    mag_b = sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _retrieve_context(session_id: str, user_message: str) -> str:
    with _vector_store_lock:
        docs = _session_vector_store.get(session_id, [])

    if not docs:
        return ""

    query_vector = _embed_texts([user_message])[0]
    ranked = sorted(
        docs,
        key=lambda doc: _cosine_similarity(query_vector, doc["embedding"]),
        reverse=True,
    )
    use_vector_search = all(doc.get("embedding") for doc in docs)

    if use_vector_search:
        try:
            query_vector = client.embeddings(model=EMBED_MODEL, prompt=user_message)["embedding"]
            ranked = sorted(
                docs,
                key=lambda doc: _cosine_similarity(query_vector, doc["embedding"]),
                reverse=True,
            )
        except Exception as exc:
            logger.warning(
                "Falling back to keyword retrieval because embedding lookup failed: %s",
                exc,
            )
            ranked = sorted(
                docs,
                key=lambda doc: _keyword_overlap_score(user_message, doc["text"]),
                reverse=True,
            )
    else:
        ranked = sorted(
            docs,
            key=lambda doc: _keyword_overlap_score(user_message, doc["text"]),
            reverse=True,
        )

    selected = [entry["text"] for entry in ranked[:RAG_RESULTS]]
    if not selected:
        return ""

    return "\n\n".join([f"[Context {idx + 1}] {text}" for idx, text in enumerate(selected)])


def _is_probably_text_file(path: str) -> bool:
    extension = os.path.splitext(path)[1].lower()
    if extension in GIT_TEXT_EXTENSIONS:
        return True

    basename = os.path.basename(path).lower()
    return basename in {"dockerfile", "makefile", "readme", "license"}


def _load_git_repo_texts(repo_path: str) -> tuple[list[str], int, int]:
    texts = []
    total_files = 0
    total_bytes = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [dir_name for dir_name in dirs if dir_name != ".git"]

        for filename in files:
            if total_files >= MAX_GIT_FILES or total_bytes >= MAX_GIT_TOTAL_TEXT_BYTES:
                return texts, total_files, total_bytes

            absolute_path = os.path.join(root, filename)
            relative_path = os.path.relpath(absolute_path, repo_path)
            total_files += 1

            if not _is_probably_text_file(absolute_path):
                continue

            try:
                file_size = os.path.getsize(absolute_path)
            except OSError:
                continue

            if file_size > MAX_GIT_FILE_SIZE_BYTES:
                continue

            try:
                with open(absolute_path, "r", encoding="utf-8") as repo_file:
                    content = repo_file.read()
            except (UnicodeDecodeError, OSError):
                continue

            content = content.strip()
            if not content:
                continue

            remaining = MAX_GIT_TOTAL_TEXT_BYTES - total_bytes
            if remaining <= 0:
                return texts, total_files, total_bytes

            limited_content = content[:remaining]
            total_bytes += len(limited_content)
            texts.append(f"File: {relative_path}\n\n{limited_content}")

    return texts, total_files, total_bytes


def _index_git_repository(session_id: str, repo_url: str) -> tuple[int, int]:
    if not GIT_EXECUTABLE:
        raise RuntimeError("Git executable not found on PATH.")

    safe_repo_url = _validate_git_repo_url(repo_url)
    with tempfile.TemporaryDirectory(prefix="holly-git-") as clone_parent:
        clone_path = os.path.join(clone_parent, "repo")
        subprocess.run(
            [GIT_EXECUTABLE, "clone", "--depth", "1", safe_repo_url, clone_path],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )  # nosec B603 - shell=False, absolute git path, and validated repo URL scheme/host.

        texts, scanned_files, total_text_bytes = _load_git_repo_texts(clone_path)
        if not texts:
            raise ValueError("No UTF-8 text files were found to index in the repository.")

        chunks = []
        for text in texts:
            chunks.extend(_chunk_text(text))

        if not chunks:
            raise ValueError("Repository files were read but no indexable chunks were produced.")

        try:
            vectors = _embed_texts(chunks)
        except Exception as exc:
            if _is_embedding_not_supported_error(exc):
                logger.warning(
                    "Embedding model '%s' does not support embeddings; indexing repository '%s' without vectors.",
                    EMBED_MODEL,
                    repo_url,
                )
                vectors = [None] * len(chunks)
            else:
                logger.exception("Failed to embed git repository '%s'.", repo_url)
                raise RuntimeError(
                    "Unable to embed cloned repository right now. "
                    f"Embedding service error: {exc}"
                ) from exc

        docs = [{"text": chunk, "embedding": vector} for chunk, vector in zip(chunks, vectors)]

        with _vector_store_lock:
            existing = _session_vector_store.get(session_id, [])
            _session_vector_store[session_id] = existing + docs

    logger.info(
        "Indexed git repository '%s': scanned=%d, text_bytes=%d, chunks=%d",
        repo_url,
        scanned_files,
        total_text_bytes,
        len(chunks),
    )
    return scanned_files, len(chunks)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    return response

@app.route("/")
def index():
    return render_template("index.html", frontend_tts_autoplay=FRONTEND_TTS_AUTOPLAY)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/upload", methods=["POST"])
def upload_file():
    client_key = _client_rate_limit_key()
    limited, retry_after = _check_rate_limit(
        "upload",
        client_key,
        RATE_LIMIT_UPLOAD_MAX,
        RATE_LIMIT_UPLOAD_WINDOW_SECONDS,
    )
    if limited:
        return (
            jsonify(
                {
                    "error": (
                        "Rate limit exceeded for uploads. "
                        f"Try again in about {retry_after} seconds."
                    )
                }
            ),
            429,
        )

    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400

    uploaded_file = request.files["file"]
    if uploaded_file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    raw_content = uploaded_file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(raw_content) > MAX_FILE_SIZE_BYTES:
        return jsonify({"error": "File too large (max 2MB)."}), 400

    try:
        text = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"error": "Only UTF-8 text files are supported."}), 400

    text = text.strip()
    if not text:
        return jsonify({"error": "Uploaded file is empty."}), 400

    if len(text) > MAX_FILE_TEXT_LENGTH:
        text = text[:MAX_FILE_TEXT_LENGTH]

    chunks = _chunk_text(text)
    if not chunks:
        return jsonify({"error": "Unable to chunk file content."}), 400

    try:
        vectors = _embed_texts(chunks)
    except Exception as exc:
        if _is_embedding_not_supported_error(exc):
            logger.warning(
                "Embedding model '%s' does not support embeddings; indexing '%s' without vectors.",
                EMBED_MODEL,
                uploaded_file.filename,
            )
            vectors = [None] * len(chunks)
        else:
            logger.exception("Failed to embed uploaded file '%s'.", uploaded_file.filename)
            return (
                jsonify(
                    {
                        "error": (
                            "Unable to process uploaded file right now. "
                            f"Embedding service error: {exc}"
                        )
                    }
                ),
                502,
            )
    session_id = _get_session_id()
    docs = [{"text": chunk, "embedding": vector} for chunk, vector in zip(chunks, vectors)]

    with _vector_store_lock:
        _session_vector_store[session_id] = docs

    return jsonify(
        {
            "message": f"Indexed '{uploaded_file.filename}' with {len(chunks)} chunks.",
            "chunks": len(chunks),
        }
    )


@app.route("/question-history", methods=["GET"])
def get_question_history():
    session_id = _get_session_id()
    return jsonify({"history": _get_question_history(session_id)})


@app.route("/text-to-speech", methods=["POST"])
def text_to_speech_proxy():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}

    fallback_text = ""
    if isinstance(payload, dict):
        fallback_text = str(
            payload.get("text")
            or payload.get("input")
            or payload.get("message")
            or ""
        ).strip()

    if TTS_MODE == "qwen3":
        if not QWEN_TTS_HEALTH_URL or not QWEN3_TTS_SPEAK_URL:
            return jsonify({"error": "QWEN_TTS_API_BASE is not configured."}), 503

        try:
            safe_health_url = _validate_outbound_http_url(QWEN_TTS_HEALTH_URL)
            health_req = urllib_request.Request(safe_health_url, method="GET")
            with urllib_request.urlopen(health_req, timeout=5):  # nosec B310 - URL is validated by _validate_outbound_http_url.
                pass
        except Exception as exc:
            logger.warning("QWEN TTS health check failed: %s", exc)
            return jsonify(
                {
                    "fallback": "browser_speak",
                    "text": fallback_text,
                    "reason": f"TTS health check failed: {exc}",
                }
            ), 200

        target_tts_url = QWEN3_TTS_SPEAK_URL
    else:
        if not QWEN_TTS_URL:
            return jsonify({"error": "QWEN_TTS_API_BASE is not configured."}), 503
        target_tts_url = QWEN_TTS_URL

    try:
        safe_url = _validate_outbound_http_url(target_tts_url)
    except ValueError as exc:
        logger.error("Invalid QWEN TTS URL '%s': %s", target_tts_url, exc)
        return jsonify({"error": f"Invalid QWEN TTS URL: {exc}"}), 500

    req = urllib_request.Request(
        safe_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    def _urlopen_and_read_with_deadline() -> tuple[bytes, int, str]:
        result_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def _worker() -> None:
            try:
                with urllib_request.urlopen(req, timeout=TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS) as upstream:  # nosec B310 - URL is validated by _validate_outbound_http_url.
                    body = upstream.read()
                    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
                    result_queue.put(("ok", (body, upstream.status, content_type)))
            except Exception as exc:
                result_queue.put(("error", exc))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        try:
            kind, value = result_queue.get(timeout=TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS)
        except queue.Empty as exc:
            raise TimeoutError(
                f"TTS upstream exceeded total timeout of {TTS_UPSTREAM_TOTAL_TIMEOUT_SECONDS:.2f}s"
            ) from exc

        if kind == "error":
            if isinstance(value, Exception):
                raise value
            raise RuntimeError(f"Unexpected upstream error payload type: {type(value)!r}")

        if not isinstance(value, tuple) or len(value) != 3:
            raise RuntimeError("Unexpected upstream success payload shape.")
        body, status, content_type = value
        return body, status, content_type

    try:
        body, status, content_type = _urlopen_and_read_with_deadline()
        return Response(body, status=status, content_type=content_type)
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.warning("QWEN TTS upstream error: %s %s", exc.code, error_body)
        return jsonify(
            {
                "fallback": "browser_speak",
                "text": fallback_text,
                "reason": f"TTS upstream HTTP {exc.code}",
                "upstreamError": error_body,
            }
        ), 200
    except Exception as exc:
        logger.exception("QWEN TTS proxy failed.")
        return jsonify(
            {
                "fallback": "browser_speak",
                "text": fallback_text,
                "reason": f"Unable to reach TTS backend: {exc}",
            }
        ), 200


def sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/stream", methods=["POST"])
def stream():
    client_key = _client_rate_limit_key()
    stream_limited, stream_retry_after = _check_rate_limit(
        "stream",
        client_key,
        RATE_LIMIT_STREAM_MAX,
        RATE_LIMIT_STREAM_WINDOW_SECONDS,
    )
    if stream_limited:
        return Response(
            sse(
                {
                    "type": "error",
                    "error": (
                        "Rate limit exceeded for streaming requests. "
                        f"Try again in about {stream_retry_after} seconds."
                    ),
                }
            ),
            status=429,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    content_length = request.content_length or 0
    if content_length > MAX_STREAM_BODY_BYTES:
        return Response(
            sse({"type": "error", "error": "Request body is too large."}),
            status=413,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    payload = request.get_json(silent=True) or {}
    user_message = payload.get("message")

    if not isinstance(user_message, str) or not user_message.strip():
        error_payload = {
            "type": "error",
            "error": "Invalid message: must be a non-empty string.",
        }
        return Response(
            sse(error_payload),
            status=400,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    user_message = user_message.strip()
    request_session_id = _get_session_id()
    logger.info(
        "Incoming /stream request session debug: flask_session_id=%s has_cookie=%s remote_addr=%s",
        _short_session(request_session_id),
        bool(request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "session"))),
        request.remote_addr,
    )
    _append_question_history(session_id=request_session_id, question=user_message)

    if user_message == "/help":
        return Response(
            sse({"type": "token", "content": HELP_MESSAGE}) + sse({"type": "done"}),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if user_message == "/models":
        try:
            models = _list_available_models()
        except Exception as exc:
            # Return a normal token/done response so the UI doesn't show a streaming failure.
            current_model = OPENCLAW_AGENT_MODEL if OLLAMA_BEARER_TOKEN else OLLAMA_MODEL
            fallback_candidates = [current_model]
            if OLLAMA_MODEL and OLLAMA_MODEL not in fallback_candidates:
                fallback_candidates.append(OLLAMA_MODEL)

            fallback_lines = "\n".join(f"- {model}" for model in fallback_candidates if model)
            fallback = (
                f"Current model: {current_model}\n"
                "Available models (fallback):\n"
                f"{fallback_lines}\n"
                f"(Could not fetch backend model catalog: {exc})"
            )
            return Response(
                sse({"type": "token", "content": fallback}) + sse({"type": "done"}),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        if models:
            model_lines = "\n".join(f"- {model}" for model in models)
            current_model = OPENCLAW_AGENT_MODEL if OLLAMA_BEARER_TOKEN else OLLAMA_MODEL
            content = (
                f"Current model: {current_model}\n"
                "Available models:\n"
                f"{model_lines}"
            )
        else:
            content = "No models were returned by the configured API endpoint."

        return Response(
            sse({"type": "token", "content": content}) + sse({"type": "done"}),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if user_message == "/clear":
        session_id = _get_session_id()
        with _vector_store_lock:
            _session_vector_store.pop(session_id, None)

        return Response(
            sse({"type": "token", "content": "Knowledge base cleared for this session."})
            + sse({"type": "done"}),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if user_message == "/vectordb":
        stats = _vector_store_stats()
        session_lines = [
            f"- {_masked_session_suffix(sid)}: {count} chunks"
            for sid, count in sorted(
                stats["session_chunk_counts"].items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]
        sessions_summary = "\n".join(session_lines) if session_lines else "- none"

        return Response(
            sse(
                {
                    "type": "token",
                    "content": (
                        "Vector DB stats:\n"
                        f"- total chunks: {stats['total_chunks']}\n"
                        f"- open sessions: {stats['open_sessions']}\n"
                        "- sessions:\n"
                        f"{sessions_summary}"
                    ),
                }
            )
            + sse({"type": "done"}),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    session_id = request_session_id

    if user_message.startswith("/git"):
        if not GIT_ENDPOINT_TOKEN:
            return Response(
                sse({"type": "error", "error": "The /git endpoint is disabled by server configuration."}),
                status=503,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        provided_git_token = _extract_git_auth_token()
        if not provided_git_token or not secrets.compare_digest(provided_git_token, GIT_ENDPOINT_TOKEN):
            return Response(
                sse({"type": "error", "error": "Unauthorized"}),
                status=401,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        git_limited, git_retry_after = _check_rate_limit(
            "git",
            client_key,
            RATE_LIMIT_GIT_MAX,
            RATE_LIMIT_GIT_WINDOW_SECONDS,
        )
        if git_limited:
            return Response(
                sse(
                    {
                        "type": "error",
                        "error": (
                            "Rate limit exceeded for /git requests. "
                            f"Try again in about {git_retry_after} seconds."
                        ),
                    }
                ),
                status=429,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        parts = user_message.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return Response(
                sse({"type": "error", "error": "Usage: /git <repository-url>"}),
                status=400,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        repo_url = parts[1].strip()

        try:
            scanned_files, indexed_chunks = _index_git_repository(session_id, repo_url)
            return Response(
                sse(
                    {
                        "type": "token",
                        "content": (
                            f"Indexed repository '{repo_url}'. "
                            f"Scanned {scanned_files} files and stored {indexed_chunks} chunks for RAG queries."
                        ),
                    }
                )
                + sse({"type": "done"}),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        except subprocess.TimeoutExpired:
            return Response(
                sse({"type": "error", "error": "Git clone timed out while fetching the repository."}),
                status=504,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            return Response(
                sse({"type": "error", "error": f"Git clone failed: {details}"}),
                status=400,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        except (ValueError, RuntimeError) as exc:
            return Response(
                sse({"type": "error", "error": str(exc)}),
                status=400,
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

    if len(user_message) > MAX_MESSAGE_LENGTH:
        error_payload = {
            "type": "error",
            "error": f"Invalid message: exceeds max length ({MAX_MESSAGE_LENGTH} characters).",
        }
        return Response(
            sse(error_payload),
            status=400,
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    def generate():
        try:
            context = _retrieve_context(session_id, user_message)

            final_prompt = user_message
            if context:
                final_prompt = (
                    "Use the provided context to answer the user's question. "
                    "If context is not relevant, respond normally.\n\n"
                    f"{context}\n\nUser question: {user_message}"
                )

            for content in _stream_chat_tokens(final_prompt, session_id=session_id):
                yield sse({"type": "token", "content": content})

            yield sse({"type": "done"})

        except Exception:
            logger.exception("Unhandled error while generating stream response.")
            yield sse({"type": "error", "error": "Unable to process request right now."})

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
