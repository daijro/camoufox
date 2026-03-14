#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VERSION="official/stable"
HEADFUL=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --browser-version)
            VERSION="$2"
            shift 2
            ;;
        --headful)
            HEADFUL="--headful"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--browser-version <specifier>] [--headful]"
            echo "  e.g. $0 --browser-version official/prerelease/146.0.1-beta.25 --headful"
            exit 1
            ;;
    esac
done

echo "==> Browser version: $VERSION"

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"

echo "==> Installing camoufox from local source..."
$PIP install -q -e ../pythonlib

echo "==> Setting browser version: $VERSION"
$PYTHON -m camoufox set "$VERSION"

echo "==> Fetching browser..."
$PYTHON -m camoufox fetch

echo "==> Installing test dependencies..."
$PIP install -q -r requirements.txt

echo "==> Running tests..."
.venv/bin/pytest test_fingerprints.py -v -s --browser-version "$VERSION" $HEADFUL
