#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="malithwishwa02-dot"
REPO_NAME="Lucid"
KEY_PATH="$HOME/.ssh/id_ed25519_lucid.pub"
TITLE="Codespace deploy key"

if [ ! -f "$KEY_PATH" ]; then
  echo "ERROR: Public key not found at $KEY_PATH" >&2
  exit 1
fi

echo "This script will add $KEY_PATH as a deploy key to $REPO_OWNER/$REPO_NAME"
read -p "Proceed? (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborting."
  exit 0
fi

read -rs -p "Paste a Personal Access Token (with repo admin access) and press Enter: " TOKEN
echo
PUBLIC_KEY=$(cat "$KEY_PATH")

PAYLOAD=$(jq -n --arg title "$TITLE" --arg key "$PUBLIC_KEY" '{title: $title, key: $key, read_only: false}')

echo "Adding deploy key..."

HTTP_STATUS=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
  -H "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/keys \
  -d "$PAYLOAD")

if [ "$HTTP_STATUS" -eq 201 ]; then
  echo "Deploy key added successfully."
else
  echo "Failed to add deploy key. HTTP status: $HTTP_STATUS" >&2
  echo "Response body:" >&2
  curl -sS -X POST \
    -H "Authorization: token $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/keys \
    -d "$PAYLOAD" || true
  exit 1
fi
