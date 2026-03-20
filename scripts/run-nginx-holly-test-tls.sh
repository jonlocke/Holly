#!/usr/bin/env bash
set -euo pipefail

# Manage an nginx TLS reverse-proxy container that maps:
#   https://holly/test  ->  http://holly-test:5000
#
# Usage:
#   ./run-nginx-holly-test-tls.sh start    # create/update and run (default)
#   ./run-nginx-holly-test-tls.sh stop     # stop container (keeps config/certs)
#   ./run-nginx-holly-test-tls.sh disable  # disable auto-restart + stop + remove container

CONTAINER_NAME="holly-test-nginx-tls"
NETWORK_NAME="tts-net"
BASE_DIR="${HOME}/Holly/scripts/nginx-holly-test-tls"
CONF_DIR="${BASE_DIR}/conf.d"
CERT_DIR="${BASE_DIR}/certs"

ACTION="${1:-start}"

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"
}

do_start() {
  mkdir -p "${CONF_DIR}" "${CERT_DIR}"

  # Ensure network exists
  if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
    echo "[+] Creating docker network: ${NETWORK_NAME}"
    docker network create "${NETWORK_NAME}"
  else
    echo "[=] Docker network exists: ${NETWORK_NAME}"
  fi

  # Create self-signed cert for hostname 'holly' if missing
  CRT="${CERT_DIR}/holly.crt"
  KEY="${CERT_DIR}/holly.key"
  if [[ ! -f "${CRT}" || ! -f "${KEY}" ]]; then
    echo "[+] Generating self-signed TLS certificate for CN=holly"
    openssl req -x509 -nodes -newkey rsa:2048 \
      -keyout "${KEY}" \
      -out "${CRT}" \
      -days 825 \
      -subj "/CN=holly" \
      -addext "subjectAltName=DNS:holly"
  else
    echo "[=] Reusing existing TLS certs in ${CERT_DIR}"
  fi

  # Write nginx server config
  cat > "${CONF_DIR}/default.conf" <<'NGINX_CONF'
server {
    listen 443 ssl;
    server_name holly;

    ssl_certificate     /etc/nginx/certs/holly.crt;
    ssl_certificate_key /etc/nginx/certs/holly.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location = /test {
        return 301 /test/;
    }

    location /test/ {
        proxy_pass http://holly-test:5000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Prefix /test;

        proxy_buffering off;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
NGINX_CONF

  # Replace existing container with fresh config
  if container_exists; then
    echo "[+] Removing existing container: ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" >/dev/null
  fi

  echo "[+] Starting nginx TLS container: ${CONTAINER_NAME}"
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    --network "${NETWORK_NAME}" \
    -p 443:443 \
    -v "${CONF_DIR}/default.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "${CERT_DIR}:/etc/nginx/certs:ro" \
    nginx:stable >/dev/null

  echo "[✓] Started"
  echo "    URL: https://holly/test"
}

do_stop() {
  if container_exists; then
    echo "[+] Stopping container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}" >/dev/null
    echo "[✓] Stopped"
  else
    echo "[=] Container not found: ${CONTAINER_NAME}"
  fi
}

do_disable() {
  if container_exists; then
    echo "[+] Disabling auto-restart: ${CONTAINER_NAME}"
    docker update --restart=no "${CONTAINER_NAME}" >/dev/null
    echo "[+] Stopping container: ${CONTAINER_NAME}"
    docker stop "${CONTAINER_NAME}" >/dev/null || true
    echo "[+] Removing container: ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" >/dev/null || true
    echo "[✓] Disabled (container removed, config/certs kept)"
  else
    echo "[=] Container not found: ${CONTAINER_NAME}"
    echo "[✓] Nothing to disable"
  fi
}

case "${ACTION}" in
  start)
    do_start
    ;;
  stop)
    do_stop
    ;;
  disable)
    do_disable
    ;;
  *)
    echo "Usage: $0 {start|stop|disable}"
    exit 1
    ;;
esac
