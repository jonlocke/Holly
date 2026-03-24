#!/bin/bash
set -euo pipefail
#set -x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

# --- Clean up container ---
sudo docker rm -f holly-test 2>/dev/null || true

# --- Update repo ---
git fetch --all --prune

# --- Get branch list ---
mapfile -t branches < <(
  {
    git for-each-ref --format='%(refname:short)' refs/heads/
    git for-each-ref --format='%(refname:short)' refs/remotes/origin/ \
      | sed 's#^origin/##' \
      | grep -v '^HEAD$'
  } | sort -u
)

echo "Available branches:"
for i in "${!branches[@]}"; do
  echo "$((i+1))) ${branches[$i]}"
done

# --- Prompt user ---
read -p "Select branch number to build: " choice

# --- Validate input ---
if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#branches[@]}" ]; then
  echo "Invalid selection"
  exit 1
fi

selected_branch="${branches[$((choice-1))]}"
echo "Switching to branch: $selected_branch"

# --- Switch branch ---
if git show-ref --verify --quiet "refs/heads/${selected_branch}"; then
  git switch "$selected_branch"
else
  git switch -c "$selected_branch" --track "origin/$selected_branch"
fi

# Optional: pull latest for that branch
git pull

# --- Build and run ---
"${SCRIPT_DIR}/build-docker.sh"
"${SCRIPT_DIR}/docker-run-test.sh"
