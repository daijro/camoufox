#!/usr/bin/env bash
# Camoufox test runner.
#
# Pulls microsoft/playwright-python at the tag matching the installed
# playwright package, then runs both that upstream suite and our
# Camoufox-specific tests against the Camoufox binary.
#
# Usage:
#   ./run-tests.sh --executable-path /path/to/camoufox [options]
#
# Options:
#   --executable-path PATH    Path to Camoufox binary (required unless CAMOUFOX_EXECUTABLE_PATH is set)
#   --headful                 Disable headless mode (needs DISPLAY or xvfb-run)
#   --camoufox-only           Skip the upstream Playwright suite, only run tests-camoufox/
#   --upstream-only           Skip Camoufox-specific tests, only run upstream
#   -k EXPR / -m EXPR         Forwarded to pytest
#   -n N                      pytest-xdist parallelism (default: 8)
#   --help                    Show this message
#
# Environment:
#   CAMOUFOX_EXECUTABLE_PATH  Same as --executable-path
#   PLAYWRIGHT_TAG            Override the upstream tag (default: auto-detect from installed playwright)
#   UPSTREAM_CACHE_DIR        Where to store the cloned upstream (default: tests-camoufox/.upstream-cache)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- arg parsing ----------
EXEC_PATH="${CAMOUFOX_EXECUTABLE_PATH:-}"
HEADFUL=0
CAMOUFOX_ONLY=0
UPSTREAM_ONLY=0
PYTEST_PASSTHROUGH=()
PARALLEL="${PYTEST_PARALLEL:-8}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --executable-path)
            EXEC_PATH="$2"; shift 2 ;;
        --headful)
            HEADFUL=1; shift ;;
        --camoufox-only)
            CAMOUFOX_ONLY=1; shift ;;
        --upstream-only)
            UPSTREAM_ONLY=1; shift ;;
        -k|-m)
            PYTEST_PASSTHROUGH+=("$1" "$2"); shift 2 ;;
        -n)
            PARALLEL="$2"; shift 2 ;;
        --help|-h)
            sed -n '2,/^set -/p' "$0" | sed 's/^# \?//; /^set -/d'
            exit 0 ;;
        *)
            PYTEST_PASSTHROUGH+=("$1"); shift ;;
    esac
done

if [[ -z "$EXEC_PATH" ]]; then
    echo "ERROR: --executable-path required (or set CAMOUFOX_EXECUTABLE_PATH)" >&2
    exit 1
fi
if [[ ! -x "$EXEC_PATH" ]]; then
    echo "ERROR: $EXEC_PATH is not an executable" >&2
    exit 1
fi
export CAMOUFOX_EXECUTABLE_PATH="$EXEC_PATH"

# ---------- venv ----------
if [[ ! -d venv ]]; then
    echo "==> Creating venv..."
    bash setup-venv.sh
fi
PYTHON="venv/bin/python"
PYTEST="venv/bin/pytest"

# ---------- resolve upstream tag ----------
TAG="${PLAYWRIGHT_TAG:-}"
if [[ -z "$TAG" ]]; then
    TAG="v$($PYTHON -c 'from importlib.metadata import version; print(version("playwright"))')"
fi
echo "==> Targeting upstream microsoft/playwright-python@$TAG"

# ---------- fetch upstream tests ----------
CACHE_DIR="${UPSTREAM_CACHE_DIR:-$SCRIPT_DIR/.upstream-cache}"
UPSTREAM_DIR="$CACHE_DIR/$TAG"
if [[ ! -d "$UPSTREAM_DIR/tests" ]]; then
    echo "==> Fetching upstream playwright-python@$TAG into $UPSTREAM_DIR..."
    mkdir -p "$UPSTREAM_DIR"
    curl -sL "https://api.github.com/repos/microsoft/playwright-python/tarball/$TAG" \
        | tar -xz --strip-components=1 -C "$UPSTREAM_DIR"
    if [[ ! -d "$UPSTREAM_DIR/tests" ]]; then
        echo "ERROR: upstream tarball did not contain a tests/ directory" >&2
        exit 1
    fi
    # Upstream's source tree contains a `playwright/` package skeleton that
    # shadows our installed package when pytest runs with cwd inside the
    # tarball. Two files are missing from the skeleton vs. an installed copy
    # (_repo_version.py + the bundled driver/). Move the skeleton aside —
    # we want the installed package only.
    if [[ -d "$UPSTREAM_DIR/playwright" ]]; then
        mv "$UPSTREAM_DIR/playwright" "$UPSTREAM_DIR/.playwright-source-skeleton"
    fi
else
    echo "==> Using cached upstream at $UPSTREAM_DIR"
fi

# ---------- assemble pytest args ----------
PYTEST_ARGS=(
    --timeout=60
    --tb=line
    -p no:cacheprovider
    -n "$PARALLEL"
    # Retry flaky failures up to 3 times before declaring real failure.
    # The Playwright suite has nontrivial run-to-run variance under -n 8
    # (page clock timing, tracing event ordering, network races) — upstream
    # uses the same approach in their CI.
    --reruns 3
    --reruns-delay 1
)

# Upstream parametrises tests across chromium/firefox/webkit by default;
# Camoufox only matters under firefox.
UPSTREAM_PYTEST_ARGS=(--browser firefox)

# Upstream's pyproject.toml hard-codes -vv -s -Wall via addopts, which is
# unusable in CI. -o addopts="" cancels those.
UPSTREAM_PYTEST_ARGS+=(-o "addopts=")

if [[ $HEADFUL -eq 1 ]]; then
    PYTEST_ARGS+=(--headed)
fi

# Known-failures deselect file (one test ID per line, # comments allowed)
KF_FILE="$SCRIPT_DIR/known-failures-$TAG.txt"
if [[ -f "$KF_FILE" ]]; then
    while IFS= read -r line; do
        line="${line%%#*}"; line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" ]] && continue
        PYTEST_ARGS+=(--deselect "$line")
    done < "$KF_FILE"
fi

# Camoufox conftest plugin path
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH+:$PYTHONPATH}"

# ---------- run upstream suite ----------
UPSTREAM_RC=0
if [[ $CAMOUFOX_ONLY -eq 0 ]]; then
    echo "==> Running upstream Playwright suite against Camoufox..."
    pushd "$UPSTREAM_DIR" >/dev/null
    "$SCRIPT_DIR/$PYTEST" \
        "${PYTEST_ARGS[@]}" \
        "${UPSTREAM_PYTEST_ARGS[@]}" \
        -p camoufox_plugin \
        "${PYTEST_PASSTHROUGH[@]}" \
        tests/async/ \
        || UPSTREAM_RC=$?
    popd >/dev/null
fi

# ---------- run camoufox-specific tests ----------
CF_RC=0
if [[ $UPSTREAM_ONLY -eq 0 ]]; then
    echo "==> Running Camoufox-specific tests..."
    "$PYTEST" \
        "${PYTEST_ARGS[@]}" \
        "${PYTEST_PASSTHROUGH[@]}" \
        "$SCRIPT_DIR" \
        || CF_RC=$?
fi

# ---------- exit code ----------
if [[ $UPSTREAM_RC -ne 0 || $CF_RC -ne 0 ]]; then
    echo "FAILED — upstream rc=$UPSTREAM_RC, camoufox rc=$CF_RC"
    exit 1
fi
echo "OK"
