#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD_TESTER_DIR="$SCRIPT_DIR/../build-tester"

VERSION="official/stable"
EXECUTABLE_PATH=""
HEADFUL=""
PROFILE_COUNT=6
PROXIES="$SCRIPT_DIR/proxies.txt"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --browser-version)
            VERSION="$2"
            shift 2
            ;;
        --executable-path)
            EXECUTABLE_PATH="$2"
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
            EXTRA_ARGS+=("--no-cert")
            shift
            ;;
        --save-cert)
            EXTRA_ARGS+=("--save-cert" "$2")
            shift 2
            ;;
        -h|--help)
            cat <<EOF
Usage: $0 [options]
  --executable-path PATH     Path to a local Camoufox binary (skips fetch).
                             Use this to test a binary you built locally.
  --browser-version VER      Camoufox version specifier (default: official/stable).
                             Ignored when --executable-path is set.
  --profile-count N          Number of profiles to test (default: 6)
  --proxies PATH             Path to proxies.txt (default: ./proxies.txt)
  --headful                  Run with visible browser window
  --no-cert                  Skip certificate generation
  --save-cert PATH           Save certificate text to PATH
EOF
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Run '$0 --help' for usage." >&2
            exit 1
            ;;
    esac
done

if [ -n "$EXECUTABLE_PATH" ]; then
    echo "==> Executable path: $EXECUTABLE_PATH"
    if [ ! -e "$EXECUTABLE_PATH" ]; then
        echo "ERROR: --executable-path does not exist: $EXECUTABLE_PATH" >&2
        exit 1
    fi
else
    echo "==> Browser version: $VERSION"
fi
echo "==> Profile count:   $PROFILE_COUNT"

if [ ! -d "$BUILD_TESTER_DIR/node_modules" ]; then
    echo "==> Installing build-tester npm dependencies..."
    (cd "$BUILD_TESTER_DIR" && npm install --silent)
fi

if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv .venv
fi

PYTHON=".venv/bin/python"
PIP=".venv/bin/pip"

echo "==> Installing camoufox from local source..."
$PIP uninstall -y cloverlabs-camoufox >/dev/null 2>&1 || true
$PIP install -q -e ../pythonlib

if [ -z "$EXECUTABLE_PATH" ]; then
    echo "==> Setting browser version: $VERSION"
    $PYTHON -m camoufox set "$VERSION"

    echo "==> Fetching browser..."
    $PYTHON -m camoufox fetch

    # Verify fetch actually installed the requested version (it silently no-ops on unknown versions)
    ACTIVE=$($PYTHON -m camoufox active 2>/dev/null | tr -d '[:space:]' || true)
    REQUESTED_TAIL="${VERSION##*/}"
    if [ -n "$REQUESTED_TAIL" ] && [[ "$REQUESTED_TAIL" != stable && "$REQUESTED_TAIL" != prerelease && "$REQUESTED_TAIL" != *channel* ]]; then
        if ! echo "$ACTIVE" | grep -qi "$REQUESTED_TAIL"; then
            echo "WARNING: requested '$VERSION' but active version is '$ACTIVE'." >&2
            echo "         The version was probably not found in the registered repos." >&2
            echo "         Run '$PYTHON -m camoufox list all' to see available versions," >&2
            echo "         or pass --executable-path to use a locally built binary." >&2
        fi
    fi
fi

echo "==> Running service tests..."
EXEC_ARG=()
if [ -n "$EXECUTABLE_PATH" ]; then
    EXEC_ARG=(--executable-path "$EXECUTABLE_PATH")
fi
$PYTHON run_tests.py \
    --browser-version "$VERSION" \
    --profile-count "$PROFILE_COUNT" \
    --proxies "$PROXIES" \
    $HEADFUL \
    "${EXEC_ARG[@]}" \
    "${EXTRA_ARGS[@]}"
