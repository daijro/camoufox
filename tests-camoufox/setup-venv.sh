#!/usr/bin/env bash
# Create the venv used by run-tests.sh.
#
# Two layers of deps:
#   1. local-requirements.txt — the playwright pin that drives the whole
#      harness, plus a small handful of extras we use beyond what upstream needs.
#   2. The same local-requirements.txt that microsoft/playwright-python ships
#      at the matching tag — pytest, pytest-asyncio, twisted, etc. We pull this
#      from the upstream cache (downloading it if missing) so the test deps
#      always match what upstream itself runs against. No need to maintain
#      a duplicate list here.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m venv venv
venv/bin/pip install --quiet --upgrade pip

# Step 1: install our local pins (notably, the `playwright` version).
venv/bin/pip install --quiet -r local-requirements.txt

# Step 2: resolve which upstream tag we want, then pip-install whatever
# pytest stack microsoft/playwright-python ships with for that tag.
TAG="${PLAYWRIGHT_TAG:-v$(venv/bin/python -c 'from importlib.metadata import version; print(version("playwright"))')}"
CACHE_DIR="${UPSTREAM_CACHE_DIR:-$SCRIPT_DIR/.upstream-cache}"
UPSTREAM_DIR="$CACHE_DIR/$TAG"
UPSTREAM_REQS="$UPSTREAM_DIR/local-requirements.txt"
if [[ ! -f "$UPSTREAM_REQS" ]]; then
    echo "==> Fetching upstream playwright-python@$TAG for its test requirements..."
    mkdir -p "$UPSTREAM_DIR"
    curl -sL "https://api.github.com/repos/microsoft/playwright-python/tarball/$TAG" \
        | tar -xz --strip-components=1 -C "$UPSTREAM_DIR"
    if [[ -d "$UPSTREAM_DIR/playwright" ]]; then
        mv "$UPSTREAM_DIR/playwright" "$UPSTREAM_DIR/.playwright-source-skeleton"
    fi
fi

# Filter out lint/build deps we don't need for running tests, then install.
echo "==> Installing test deps from upstream@$TAG..."
grep -vE '^(black|flake8|mypy|pre-commit|build|types-)' "$UPSTREAM_REQS" \
    | venv/bin/pip install --quiet -r /dev/stdin

# Install the playwright driver bundle (needed by Playwright Python at import
# time even though we point it at the Camoufox binary at runtime).
venv/bin/playwright install firefox
