#!/bin/bash
set -e
#set -x

# --- Clean up container ---
sudo docker rm -f holly-test 2>/dev/null || true

# --- Update repo ---
git fetch --all --prune

# --- Get branch list ---
mapfile -t branches < <(git for-each-ref --format='%(refname:short)' refs/heads/)

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
git switch "$selected_branch"

# Optional: pull latest for that branch
git pull

# --- Build and run ---
./build-docker.sh
./docker-run-test.sh
