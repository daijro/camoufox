#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BINARY=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile-count|--secret|--save-cert)
            EXTRA_ARGS+=("$1" "$2")
            shift 2
            ;;
        --no-cert)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        -h|--help)
            echo "Usage: $0 <binary_path> [--profile-count N] [--secret KEY] [--save-cert PATH] [--no-cert]"
            echo "  e.g. $0 ../camoufox-146.0.1-beta.25/obj-aarch64-apple-darwin/dist/Camoufox.app"
            exit 0
            ;;
        -*)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
        *)
            if [ -n "$BINARY" ]; then
                echo "Unexpected positional argument: $1 (binary already set to $BINARY)" >&2
                exit 1
            fi
            BINARY="$1"
            shift
            ;;
    esac
done

if [ -z "$BINARY" ]; then
    echo "ERROR: binary_path is required" >&2
    echo "Usage: $0 <binary_path> [options]" >&2
    exit 1
fi

if [ ! -d "node_modules" ]; then
    echo "==> Installing npm dependencies (esbuild)..."
    npm install --silent
fi

if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"

echo "==> Installing camoufox from local source + playwright..."
$PIP uninstall -y cloverlabs-camoufox >/dev/null 2>&1 || true
$PIP install -q -e ../pythonlib playwright

echo "==> Running build tester..."
$PYTHON scripts/run_tests.py "$BINARY" "${EXTRA_ARGS[@]}"
