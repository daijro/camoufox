#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD_TESTER_DIR="$SCRIPT_DIR/../build-tester"

VERSION="official/stable"
HEADFUL=""
PROFILE_COUNT=6
PROXIES="$SCRIPT_DIR/proxies.txt"
EXTRA_ARGS=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --browser-version)
            VERSION="$2"
            shift 2
            ;;
        --profile-count)
            PROFILE_COUNT="$2"
            shift 2
            ;;
        --proxies)
            PROXIES="$2"
            shift 2
            ;;
        --headful)
            HEADFUL="--headful"
            shift
            ;;
        --no-cert)
            EXTRA_ARGS="$EXTRA_ARGS --no-cert"
            shift
            ;;
        --save-cert)
            EXTRA_ARGS="$EXTRA_ARGS --save-cert $2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--browser-version <specifier>] [--profile-count N] [--proxies PATH] [--headful] [--no-cert] [--save-cert PATH]"
            echo "  e.g. $0 --browser-version official/prerelease/146.0.1-beta.50 --headful"
            exit 1
            ;;
    esac
done

echo "==> Browser version: $VERSION"
echo "==> Profile count:   $PROFILE_COUNT"

# Install npm deps in build-tester (for esbuild — needed to build TypeScript bundle)
if [ ! -d "$BUILD_TESTER_DIR/node_modules" ]; then
    echo "==> Installing build-tester npm dependencies..."
    (cd "$BUILD_TESTER_DIR" && npm install --silent)
fi

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"

echo "==> Installing camoufox from local source..."
$PIP uninstall -y cloverlabs-camoufox >/dev/null 2>&1 || true
$PIP install -q -e ../pythonlib

echo "==> Setting browser version: $VERSION"
$PYTHON -m camoufox set "$VERSION"

echo "==> Fetching browser..."
$PYTHON -m camoufox fetch

echo "==> Running service tests..."
$PYTHON run_tests.py \
    --browser-version "$VERSION" \
    --profile-count "$PROFILE_COUNT" \
    --proxies "$PROXIES" \
    $HEADFUL \
    $EXTRA_ARGS
