#!/bin/bash

set -u

container="${1:-}"

if [ -z "$container" ]; then
  echo "Usage: $0 <container-name-or-id>"
  exit 1
fi

echo "Looking up container: $container"

if ! docker inspect "$container" >/dev/null 2>&1; then
  echo "Error: container '$container' does not exist."
  exit 1
fi

pid="$(docker inspect --format '{{.State.Pid}}' "$container" 2>/dev/null)" || {
  echo "Error: failed to inspect container '$container'."
  exit 1
}

if [ -z "$pid" ] || [ "$pid" = "0" ]; then
  echo "Container '$container' is not running (PID=$pid)."
else
  echo "Container PID: $pid"
  if sudo kill -9 "$pid" 2>/dev/null; then
    echo "Killed PID $pid"
    sleep 5
  else
    echo "Warning: failed to kill PID $pid (it may already be gone)."
  fi
fi

if docker stop "$container" >/dev/null 2>&1; then
  echo "Stopped container '$container'"
else
  echo "Warning: docker stop failed or container was already stopped."
fi

if docker rm -f "$container" >/dev/null 2>&1; then
  echo "Removed container '$container'"
else
  echo "Error: failed to remove container '$container'"
  exit 1
fi

echo "Done."
