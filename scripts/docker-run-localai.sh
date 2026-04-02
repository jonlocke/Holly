#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${HOLLY_DATA_DIR:-${REPO_ROOT}/data/localai}"

"${SCRIPT_DIR}/killme.sh" holly5005 || true
mkdir -p "${DATA_DIR}"
chmod 0777 "${DATA_DIR}"
export OLLAMA_API_BASE=http://holly-voice:10000
export QWEN_TTS_API_BASE=http://quick-piper-endpoint:8092
docker run -d \
--restart unless-stopped \
--name holly5005 \
--network tts-net \
-p 5005:5000 \
-v "${DATA_DIR}:/data" \
-e WHISPER_CPP_STT_ENDPOINT="$WHISPER_CPP_STT_ENDPOINT" \
-e HOLLY_IDENTITY_STORE_PATH=/data/identity_store.json \
-e HOLLY_FACE_VERIFY_STORE_PATH=/data/face_verify_store.json \
-e SESSION_COOKIE_SECURE=false \
-e TTS_MODE=qwen3 \
-e QWEN3_TTS_SPEAK_QUERY="$QWEN3_TTS_SPEAK_QUERY" \
-e FRONTEND_TTS_AUTOPLAY=true \
-e QWEN_TTS_TIMEOUT_SECONDS=360 \
-e FLASK_DEBUG=1 \
-e OLLAMA_API_BASE="$OLLAMA_API_BASE" \
-e OLLAMA_MODEL="$OLLAMA_MODEL" \
-e OLLAMA_BEARER_TOKEN="$OLLAMA_BEARER_TOKEN" \
-e QWEN_TTS_API_BASE="$QWEN_TTS_API_BASE" \
-e QWEN_TTS_ENDPOINT_STYLE=quick \
-e QWEN_TTS_MODEL=qwen3-tts \
-e QWEN_TTS_VOICE=ryan \
-e QWEN_TTS_LANGUAGE=english \
holly-ux
echo "Persistent data dir: ${DATA_DIR}"
