#!/bin/bash
set -e

# --- Clean container ---
sudo docker rm -f holly-test 2>/dev/null || true

# --- Fetch latest ---
git fetch --all --prune

# --- Get branch list (local + remote) ---
mapfile -t branches < <(
  git for-each-ref --format='%(refname:short)' refs/heads/ refs/remotes/origin/ \
  | grep -v 'origin/HEAD' \
  | sed 's|^origin/||' \
  | sort -u
)

echo "Available branches:"
for i in "${!branches[@]}"; do
  echo "$((i+1))) ${branches[$i]}"
done

# --- Prompt ---
read -p "Select branch number to build: " choice

# --- Validate ---
if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#branches[@]}" ]; then
  echo "Invalid selection"
  exit 1
fi

selected_branch="${branches[$((choice-1))]}"
echo "Selected: $selected_branch"

# --- Switch or create tracking branch ---
if git show-ref --verify --quiet "refs/heads/$selected_branch"; then
  git switch "$selected_branch"
else
  echo "Creating local tracking branch for origin/$selected_branch"
  git switch -c "$selected_branch" "origin/$selected_branch"
fi

# --- Ensure fully up to date ---
git pull --ff-only

# --- Build + run ---
./build-docker.sh
./docker-run-test.sh
