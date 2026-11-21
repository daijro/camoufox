#!/usr/bin/env bash
# Build the `challenge` (cfsolve) binary that camoufox.solver drives.
#
#   scripts/setup_cfsolve.sh [--prefix DIR] [--cfsolve-src DIR] [--release|--debug]
#
# The binary lands at $PREFIX/bin/challenge (default ~/.local/bin). What that
# needs on this machine, and why:
#
#   * zig, as a C compiler. cfsolve builds BoringSSL, which needs a real
#     toolchain. A `cc` that is a bare symlink to zig does NOT work: invoked
#     under that name zig does not enter C-compiler mode and dies with
#     "unknown command: -O3". This script therefore writes a wrapper that
#     always calls `zig cc` / `zig c++` by language, and puts it first on PATH
#     only for the duration of the build.
#   * A libclang shared library, for bindgen (btls-sys generates its bindings).
#     The PyPI `libclang` wheel ships one and needs no system packages.
#   * C library headers. Zig ships its own; they are passed to bindgen through
#     BINDGEN_EXTRA_CLANG_ARGS, because there is no /usr/include to fall back on.
#
# Every one of those is detected first and reported together, so a missing
# tool fails the script immediately instead of several minutes into a build.
set -euo pipefail

PREFIX="${HOME}/.local"
CFSOLVE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/cfsolve"
PROFILE="release"

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --cfsolve-src) CFSOLVE_SRC="$2"; shift 2 ;;
    --release) PROFILE="release"; shift ;;
    --debug) PROFILE="debug"; shift ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[ -d "$CFSOLVE_SRC" ] || die "no cfsolve checkout at $CFSOLVE_SRC (clone chris124567/cfsolve, or pass --cfsolve-src)"
[ -f "$CFSOLVE_SRC/Cargo.toml" ] || die "$CFSOLVE_SRC is not a cfsolve checkout (no Cargo.toml)"

missing=()
command -v cargo >/dev/null 2>&1 || missing+=("cargo (install rustup)")
command -v zig   >/dev/null 2>&1 || missing+=("zig (a C compiler for BoringSSL, e.g. pip install ziglang)")
command -v uv    >/dev/null 2>&1 || missing+=("uv (fetches the libclang wheel)")
[ ${#missing[@]} -eq 0 ] || die "missing prerequisites: ${missing[*]}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- zig-backed C/C++ compilers ------------------------------------------------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/cc" <<'WRAP'
#!/bin/sh
exec zig cc "$@"
WRAP
cat > "$WORK/bin/c++" <<'WRAP'
#!/bin/sh
exec zig c++ "$@"
WRAP
chmod +x "$WORK/bin/cc" "$WORK/bin/c++"

# Prove the wrapper compiles before handing it to a 20-minute build.
say "checking the zig C compiler wrapper"
printf 'int main(void){return 0;}\n' > "$WORK/probe.c"
PATH="$WORK/bin:$PATH" cc -O3 -o "$WORK/probe" "$WORK/probe.c" \
  || die "the zig cc wrapper cannot compile a trivial C file"

# --- libclang for bindgen ------------------------------------------------------
if [ -z "${LIBCLANG_PATH:-}" ]; then
  say "fetching libclang for bindgen"
  uv pip install --python "$WORK/py" libclang >/dev/null 2>&1 \
    || uv pip install --target "$WORK/lc" libclang >/dev/null
  if [ -d "$WORK/lc" ]; then
    LIBCLANG_PATH="$(dirname "$(find "$WORK/lc" -name 'libclang*.so*' -print -quit)")"
  fi
fi

# --- C library headers from zig ------------------------------------------------
say "collecting zig's C headers"
ZIG_LIB="$(zig env | sed -n 's/.*"lib_dir": *"\([^"]*\)".*/\1/p')"
[ -n "$ZIG_LIB" ] || die "could not read zig's lib_dir from 'zig env'"
INCLUDES=""
for dir in \
  "$ZIG_LIB/libc/include/any-linux-any" \
  "$ZIG_LIB/libc/include/x86_64-linux-gnu" \
  "$ZIG_LIB/libc/include/generic-glibc" \
  "$ZIG_LIB/libc/include/x86_64-linux-any"; do
  [ -d "$dir" ] && INCLUDES="$INCLUDES -isystem $dir"
done
[ -n "$INCLUDES" ] || die "no C headers found under $ZIG_LIB/libc/include"

export PATH="$WORK/bin:$PATH"
export LIBCLANG_PATH="${LIBCLANG_PATH:-}"
export BINDGEN_EXTRA_CLANG_ARGS="-target x86_64-unknown-linux-gnu${INCLUDES}"

FLAGS=()
[ "$PROFILE" = "release" ] && FLAGS+=(--release)
# Keep peak memory sane: BoringSSL + wreq in one crate is what gets a 4-core box
# OOM-killed (SIGKILL from rustc) at default settings.
FLAGS+=(--config profile."${PROFILE}".package.cfsolve.codegen-units=16
        --config profile."${PROFILE}".package.cfsolve.opt-level=2
        --config profile."${PROFILE}".lto=false)

say "building cfsolve ($PROFILE) — this takes a few minutes"
(cd "$CFSOLVE_SRC" && cargo build --bin challenge "${FLAGS[@]}")

mkdir -p "$PREFIX/bin"
install -m 0755 "$CFSOLVE_SRC/target/$PROFILE/challenge" "$PREFIX/bin/challenge"
say "installed $PREFIX/bin/challenge"
"$PREFIX/bin/challenge" --help >/dev/null || die "the built binary does not run"
say "done — set CFSOLVE_BINARY=$PREFIX/bin/challenge"
