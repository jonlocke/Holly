#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE_NAME="${IMAGE_NAME:-holly-ux}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-${REPO_ROOT}/Dockerfile}"
DATA_DIR="${HOLLY_DATA_DIR:-${REPO_ROOT}/data}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not on PATH." >&2
  exit 1
fi

echo "Building Docker image ${IMAGE_NAME}:${IMAGE_TAG}..."
docker build \
  -f "${DOCKERFILE_PATH}" \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  "${REPO_ROOT}" \
  "$@"

echo

echo "Built image: ${IMAGE_NAME}:${IMAGE_TAG}"
echo "Run with: docker run --rm \
--name holly-test \
-v ${DATA_DIR}:/data \
-p 5500:5000 \
-e HOLLY_IDENTITY_STORE_PATH=/data/identity_store.json \
-e HOLLY_FACE_VERIFY_STORE_PATH=/data/face_verify_store.json \
-e FLASK_DEBUG=1 \
-e OLLAMA_API_BASE=\"http://holly:18789\" \
-e OLLAMA_MODEL=\"$OLLAMA_MODEL\" \
-e OLLAMA_BEARER_TOKEN=\"$OLLAMA_BEARER_TOKEN\" \
-e WHISPER_CPP_STT_ENDPOINT=http://holly-voice:9000/inference \
-e QWEN_TTS_API_BASE=http://holly-voice:8765 \
-e QWEN_TTS_ENDPOINT=/speak \
holly-ux"
