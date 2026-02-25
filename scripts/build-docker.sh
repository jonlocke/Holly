#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE_NAME="${IMAGE_NAME:-holly-ux}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-${REPO_ROOT}/Dockerfile}"

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
echo "Run with: docker run --rm -p 5000:5000 ${IMAGE_NAME}:${IMAGE_TAG}"
