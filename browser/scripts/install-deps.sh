#!/usr/bin/env bash
#
# Install the host build dependencies for `make dir` and `make build` on macOS
# (Homebrew), Debian/Ubuntu, Fedora/RHEL or Arch. `make bootstrap` runs this.
# mach needs Python 3.11 or newer (stdlib tomllib), which macOS's python3 is not.

set -euo pipefail

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==> WARNING:\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m==> ERROR:\033[0m %s\n' "$*" >&2; }

# Minimum Python version mach requires.
PY_MIN_MAJOR=3
PY_MIN_MINOR=11

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# rustup / cargo (all platforms)
# ---------------------------------------------------------------------------
install_rust() {
  if have rustc && have cargo; then
    log "Rust already installed ($(rustc --version))"
  else
    # cargo may be installed but not on PATH yet in this shell.
    if [ -f "$HOME/.cargo/env" ]; then
      # shellcheck disable=SC1091
      . "$HOME/.cargo/env"
    fi
    if have rustc && have cargo; then
      log "Rust found via ~/.cargo/env ($(rustc --version))"
    else
      log "Installing Rust via rustup..."
      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --default-toolchain stable
      # shellcheck disable=SC1091
      . "$HOME/.cargo/env"
      log "Installed $(rustc --version)"
    fi
  fi

  # `mach configure` aborts with "Cannot compile for <target>" without the std
  # target, and scripts/patch.py adds only the aarch64 Linux one.
  if have rustup; then
    log "Ensuring Rust Linux cross-compile targets (x86_64/aarch64)..."
    rustup target add x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu \
      || warn "Could not add Rust Linux targets; if cross-compiling to Linux, run: rustup target add x86_64-unknown-linux-gnu"
  fi
}

# ---------------------------------------------------------------------------
# Check that a Python >= 3.11 is available (mach needs tomllib).
# ---------------------------------------------------------------------------
check_python() {
  local py
  for py in python3.14 python3.13 python3.12 python3.11 python3; do
    if have "$py"; then
      if "$py" -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($PY_MIN_MAJOR, $PY_MIN_MINOR) else 1)" 2>/dev/null; then
        log "Found suitable Python: $py ($($py --version 2>&1))"
        return 0
      fi
    fi
  done
  warn "No Python >= ${PY_MIN_MAJOR}.${PY_MIN_MINOR} found on PATH."
  warn "mach requires it (stdlib 'tomllib'). Ensure a newer python3 comes first on PATH."
  return 1
}

# ---------------------------------------------------------------------------
# macOS (Homebrew)
# ---------------------------------------------------------------------------
install_macos() {
  log "Detected macOS."

  # Xcode Command Line Tools (clang, make, git, curl, rsync, unzip, tar).
  if ! xcode-select -p >/dev/null 2>&1; then
    log "Installing Xcode Command Line Tools..."
    xcode-select --install || warn "Trigger the CLT install dialog manually if this failed."
  else
    log "Xcode Command Line Tools present."
  fi

  # Homebrew
  if ! have brew; then
    log "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Make brew available in this shell for both Apple Silicon and Intel.
    if [ -x /opt/homebrew/bin/brew ]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [ -x /usr/local/bin/brew ]; then
      eval "$(/usr/local/bin/brew shellenv)"
    fi
  else
    log "Homebrew present ($(brew --version | head -1))."
  fi

  # Note: `p7zip` provides the `7z` binary the scripts call; the newer
  # `sevenzip` formula only ships `7zz`.
  local formulae=(python@3.14 aria2 p7zip msitools wget sqlite)
  log "Installing Homebrew formulae: ${formulae[*]}"
  brew install "${formulae[@]}"

  install_rust
}

# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------
install_linux() {
  log "Detected Linux."

  local debs="python3 python3-dev python3-pip p7zip-full msitools wget aria2 libsqlite3-dev build-essential make git curl unzip rsync ca-certificates"
  local rpms="python3 python3-devel p7zip msitools wget aria2 sqlite-devel gcc gcc-c++ make git curl unzip rsync ca-certificates"
  local pacman_pkgs="python python-pip p7zip msitools wget aria2 sqlite base-devel git curl unzip rsync ca-certificates"

  if have apt-get; then
    log "Using apt-get..."
    sudo apt-get update
    # shellcheck disable=SC2086
    sudo apt-get -y install $debs
  elif have dnf; then
    log "Using dnf..."
    # shellcheck disable=SC2086
    sudo dnf -y install $rpms
  elif have pacman; then
    log "Using pacman..."
    # shellcheck disable=SC2086
    sudo pacman -Sy --noconfirm $pacman_pkgs
  else
    err "No supported package manager (apt-get/dnf/pacman) found."
    exit 1
  fi

  install_rust
}

# ---------------------------------------------------------------------------
main() {
  case "$(uname -s)" in
    Darwin) install_macos ;;
    Linux)  install_linux ;;
    *)
      err "Unsupported platform: $(uname -s)"
      exit 1
      ;;
  esac

  echo
  check_python || true
  echo
  log "Dependency installation complete."
  log "If rustup was just installed, run: source \"\$HOME/.cargo/env\" (or open a new shell)."
}

main "$@"
