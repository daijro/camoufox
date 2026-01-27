#!/usr/bin/env bash
set -euo pipefail

# Helper script to authenticate GH CLI with a token, dispatch the Lucid Windows build
# workflow, and stream logs until completion. Does NOT store tokens.

WORKFLOW_NAME="Lucid Windows Native Build"
REPO="malithwishwa02-dot/Lucid"
BRANCH="main"

# --- check gh
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not found. Install from https://cli.github.com/ and authenticate." >&2
  exit 1
fi

echo "Repo: $REPO"

# --- authenticate if needed
if gh auth status 2>&1 | grep -q "not authenticated" || ! gh auth status >/dev/null 2>&1; then
  echo "You are not authenticated with GH CLI."
  echo -n "Enter GitHub token (GITHUB_TOKEN): "
  read -rs GHTOKEN
  echo
  echo "Authenticating..."
  echo "$GHTOKEN" | gh auth login --with-token || { echo "Authentication failed."; exit 1; }
else
  echo "GH CLI already authenticated."
fi

gh auth status || true

# --- dispatch workflow
echo "Dispatching workflow: $WORKFLOW_NAME (branch: $BRANCH)"
if ! gh workflow run "$WORKFLOW_NAME" --repo "$REPO" --ref "$BRANCH"; then
  echo "Failed to dispatch workflow. Ensure your token has 'workflow' and 'repo' permissions." >&2
  exit 1
fi

# Wait for run to appear and fetch its ID
echo "Waiting for workflow run to appear..."
sleep 5
RUN_ID=$(gh run list --repo "$REPO" --workflow="$WORKFLOW_NAME" --branch "$BRANCH" --limit 1 --json databaseId --jq '.[0].databaseId')
if [ -z "$RUN_ID" ] || [ "$RUN_ID" == "null" ]; then
  echo "Could not find newly dispatched run. Check the Actions tab on GitHub." >&2
  exit 1
fi

echo "Triggered run databaseId: $RUN_ID"

# Poll run status until it completes
while true; do
  STATUS_JSON=$(gh run view --repo "$REPO" "$RUN_ID" --json status,conclusion --jq '.status + ":" + (.conclusion // "")')
  echo "Run status: $STATUS_JSON"
  if [[ "$STATUS_JSON" == completed:* ]] || [[ "$STATUS_JSON" == "completed:"* ]]; then
    echo "Run completed. Fetching logs..."
    gh run view --repo "$REPO" "$RUN_ID" --log
    break
  fi
  sleep 10
done

echo "Done. If you want, run this script again to trigger another run."
