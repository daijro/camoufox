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
BINARY_MODE="both"   # local | fetched | both

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
        --binary)
            BINARY_MODE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--browser-version <specifier>] [--profile-count N] [--proxies PATH] [--headful] [--no-cert] [--save-cert PATH] [--binary local|fetched|both]"
            echo "  e.g. $0 --browser-version official/prerelease/146.0.1-beta.50 --headful"
            exit 1
            ;;
    esac
done

if [[ "$BINARY_MODE" != "local" && "$BINARY_MODE" != "fetched" && "$BINARY_MODE" != "both" ]]; then
    echo "ERROR: --binary must be 'local', 'fetched', or 'both' (got: $BINARY_MODE)" >&2
    exit 1
fi

echo "==> Browser version: $VERSION"
echo "==> Profile count:   $PROFILE_COUNT"
echo "==> Binary mode:     $BINARY_MODE"

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

echo "==> Building camoufox wheel from ../pythonlib..."
$PIP install -q build
rm -rf ../pythonlib/dist
(cd ../pythonlib && "$SCRIPT_DIR/.venv/bin/python" -m build --wheel -o dist >/dev/null)

echo "==> Installing camoufox from local wheel..."
$PIP uninstall -y camoufox cloverlabs-camoufox >/dev/null 2>&1 || true
$PIP install -q --force-reinstall ../pythonlib/dist/*.whl

# Locate locally compiled binary
#  - macOS: Camoufox.app/Contents/MacOS/camoufox (bare bin/camoufox-bin can't find dylibs)
#  - Linux: bin/camoufox-bin
LOCAL_BIN=""
if [[ "$BINARY_MODE" != "fetched" ]]; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
        LOCAL_GLOB=(../camoufox-*/obj-*-apple-darwin/dist/Camoufox.app/Contents/MacOS/camoufox)
    else
        LOCAL_GLOB=(../camoufox-*/obj-*-linux-*/dist/bin/camoufox-bin)
    fi
    # shellcheck disable=SC2012
    LOCAL_BIN=$(ls -1t "${LOCAL_GLOB[@]}" 2>/dev/null | head -1 || true)
    if [[ -z "$LOCAL_BIN" || ! -f "$LOCAL_BIN" ]]; then
        if [[ "$BINARY_MODE" == "local" ]]; then
            echo "ERROR: --binary local requested but no local build found at ${LOCAL_GLOB[0]}" >&2
            exit 1
        fi
        echo "==> No local build found — skipping local-binary phase"
        LOCAL_BIN=""
    else
        LOCAL_BIN=$(cd "$(dirname "$LOCAL_BIN")" && pwd)/$(basename "$LOCAL_BIN")
        # macOS .app: pythonlib reads properties.json from the executable's parent dir,
        # but the bundle stores it in Contents/Resources/. Copy it into MacOS/ if missing.
        if [[ "$(uname -s)" == "Darwin" ]]; then
            MACOS_DIR=$(dirname "$LOCAL_BIN")
            RESOURCES_PROPS="${MACOS_DIR%/MacOS}/Resources/properties.json"
            if [[ ! -f "$MACOS_DIR/properties.json" && -f "$RESOURCES_PROPS" ]]; then
                cp "$RESOURCES_PROPS" "$MACOS_DIR/properties.json"
                echo "==> Copied properties.json into $MACOS_DIR/"
            fi
        fi
    fi
fi

LOCAL_RC=0
FETCHED_RC=0

# ── Phase 1: locally compiled binary ─────────────────────────────────────────
if [[ -n "$LOCAL_BIN" ]]; then
    echo
    echo "════════════════════════════════════════════════════════════"
    echo "  PHASE 1/2 — Local binary: $LOCAL_BIN"
    echo "════════════════════════════════════════════════════════════"
    set +e
    $PYTHON run_tests.py \
        --executable-path "$LOCAL_BIN" \
        --profile-count "$PROFILE_COUNT" \
        --proxies "$PROXIES" \
        $HEADFUL \
        $EXTRA_ARGS
    LOCAL_RC=$?
    set -e
fi

# ── Phase 2: fetched binary (--browser-version) ──────────────────────────────
if [[ "$BINARY_MODE" != "local" ]]; then
    echo
    echo "════════════════════════════════════════════════════════════"
    echo "  PHASE 2/2 — Fetched binary: $VERSION"
    echo "════════════════════════════════════════════════════════════"
    echo "==> Setting browser version: $VERSION"
    $PYTHON -m camoufox set "$VERSION"
    echo "==> Fetching browser..."
    $PYTHON -m camoufox fetch
    set +e
    $PYTHON run_tests.py \
        --browser-version "$VERSION" \
        --profile-count "$PROFILE_COUNT" \
        --proxies "$PROXIES" \
        $HEADFUL \
        $EXTRA_ARGS
    FETCHED_RC=$?
    set -e
fi

echo
echo "════════════════════════════════════════════════════════════"
echo "  COMBINED RESULT"
echo "════════════════════════════════════════════════════════════"
[[ -n "$LOCAL_BIN"          ]] && echo "  Local binary:   exit $LOCAL_RC"
[[ "$BINARY_MODE" != "local" ]] && echo "  Fetched binary: exit $FETCHED_RC"

if (( LOCAL_RC != 0 || FETCHED_RC != 0 )); then
    exit 1
fi
exit 0
