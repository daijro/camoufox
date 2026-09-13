# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Camoufox is an anti-detect fork of Firefox for web scraping and automation. This repo is **not the Firefox source** — it is a *build system* that fetches upstream Firefox, applies a stack of patches + code additions, and produces a hardened, fingerprint-spoofing browser. The distinguishing design choice is that fingerprint spoofing happens at the **C++/Juggler implementation level**, not via injected JavaScript, so it is invisible to page-side inspection.

The actual Firefox tree lives in `camoufox-<version>-<release>/` (e.g. `camoufox-150.0.2-beta.25/`), created by the build. That directory is generated — never edit it directly to make lasting changes; changes there are captured as patches (see "Making patches" below).

`upstream.sh` pins `version` / `release`, and is sourced+exported by the `Makefile`, so those variables flow into every script.

## Build commands

The build system is designed for **Linux**. Windows and macOS binaries are **cross-compiled from Linux** — they are never built natively. (`scripts/install-deps.sh` covers macOS/Linux host dependencies for local `make dir` + bootstrap experimentation; a full production build path is Linux/Docker.)

```bash
bash scripts/install-deps.sh   # install host build deps (Python ≥3.11, Rust, aria2, p7zip, go, msitools, wget, sqlite)
make dir                       # fetch Firefox source, extract, copy additions/settings, apply all patches → touches _READY
make bootstrap                 # install system deps (apt/dnf/pacman) + run `mach bootstrap` (one-time)
make build                     # ./mach build in the source dir
make run                       # run the built browser (wipes ~/.camoufox profile)
make run args="--headless https://test.com"
python3 multibuild.py --target linux windows macos --arch x86_64 arm64 i686   # full cross-platform build + package
```

`make dir` is the pipeline that matters: `setup` (fetch tarball via `aria2c` → extract → `copy-additions.sh`) → `python3 scripts/patch.py` (applies every patch, writes `mozconfig`) → `_READY`. `mach` requires **Python ≥ 3.11** (stdlib `tomllib`); older `python3` crashes with `ModuleNotFoundError: No module named 'tomllib'`.

Docker is the portable path: `docker build -t camoufox-builder .` then `docker run -v "$(pwd)/dist:/app/dist" camoufox-builder --target <os> --arch <arch>`.

Packaging: `make package-linux|package-macos|package-windows arch=<arch>` (wraps `scripts/package.py`). Launcher (Go): `make build-launcher arch=<arch> os=<os>`.

## Working with patches (the core workflow)

Almost all browser-behavior changes are `patches/*.patch` (~49 patches: `fingerprint-injection.patch`, `webgl-spoofing.patch`, `navigator-spoofing.patch`, `webrtc-ip-spoofing.patch`, the `playwright/` and `librewolf/` and `ghostery/` subdirs, etc.). Do not hand-edit patch files.

Use the developer UI instead:

```bash
make edits          # launches scripts/developer.py — apply/undo/create/manage patches
```

- **New patch:** in the UI "Reset workspace" → edit files in `camoufox-*/` → `make build` / `make run` to test → "Write workspace to patch".
- **Edit existing patch:** "Edit a patch" (resets workspace to that patch's state) → edit → "Write workspace to patch" to overwrite.

Low-level equivalents: `make patch ./patches/x.patch`, `make unpatch ./patches/x.patch`, `make workspace ./patches/x.patch`, `make revert` (reset to `unpatched` tag), `make diff` (diff against `first-checkpoint`). The source dir is a git repo with `unpatched` / `first-checkpoint` / `checkpoint` tags used by these targets.

## Repository layout (the parts that require cross-file understanding)

- **`patches/`** — the diffs applied to Firefox source. This is where browser behavior is changed.
- **`additions/`** — whole files copied *into* the source tree (not diffs) by `scripts/copy-additions.sh`:
  - `additions/camoucfg/` — the C++ config layer. `MaskConfig.hpp` reads the spoofing config (from `CAMOU_CONFIG` env var / `camoufox.cfg`) that the patches consult at the C++ level; `MouseTrajectories.hpp` is the human-cursor algorithm.
  - `additions/juggler/` — Camoufox's patched **Juggler** (Firefox's Playwright automation protocol, the Firefox analog of CDP). This is where Playwright is made undetectable — the page agent runs in an isolated scope so injected automation JS is not visible to the page.
- **`settings/`** — `camoufox.cfg`, `chrome.css`, `properties.json`, `camoucfg.jvv`, prefs/policies. Copied into the source's `lw/` dir by `copy-additions.sh`. Edit the built config with `make edit-cfg`.
- **`scripts/`** — `patch.py` (the patcher, LibreWolf-derived), `developer.py` (the `make edits` UI), `package.py`, `copy-additions.sh`, `install-deps.sh`.
- **`pythonlib/`** — the `camoufox` PyPI package: the Playwright-compatible Python interface that generates + injects fingerprints via BrowserForge and launches the binary. `fingerprint-presets-v150.json` holds real scraped fingerprints. This is the user-facing API; the browser binary is the backend.
- **`jsonvv/`** — JSON-with-validation format library used for `camoucfg.jvv` (config schema).
- **`legacy/launcher/`** — Go launcher binary.
- **`assets/`** — `base.mozconfig` and other build inputs.

## Testing

`ci/` is the whole pipeline, and it runs identically locally and on a pull
request — see [`ci/README.md`](ci/README.md). Every gate below must pass before a
PR can merge; the workflow is `.github/workflows/tests.yml`.

- **`build-tester/`** — the raw binary directly, bypassing the Python package:
  eight fingerprint profiles, injected via `generate_context_fingerprint` +
  `addInitScript` and `CAMOU_CONFIG`. **This is the anti-detect suite** — run it
  when changing patches, C++, or the JS browser layer.
  ```bash
  python3 -m ci.run_build_tester --binary /path/to/camoufox-bin
  ```
- **`tests/patches/`** — one standalone guard per shipped spoofing behaviour
  (isolated evaluate, trusted events, fonts, mouse trajectories, touchscreen).
  The most direct evidence a Firefox bump did not neuter a patch that still
  *applies* cleanly.
  ```bash
  python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
  ```
- **Playwright** — upstream playwright-python, fetched fresh at the tag
  `ci/versions.py` resolves for the browser, with `ci/skiplist.yml` applied and
  `tests/camoufox/` overlaid. This is the automation-contract check, not the
  stealth check.
  ```bash
  make tests                # or: python3 -m ci.run_playwright --binary ...
  ```
- **`native-tests/`** — leaks, context lifetime, and the repo's own conventions.
- **`pythonlib/`**, **`service-tester/`** — the Python package and service layer.
- **stealth grade** — `ci/run_sundial.py` reports a letter grade and a count.
  Its per-vector detail never leaves that module, because this repo is public.

The Playwright suite is **not** a fork: `tests/` holds only `patches/` and
`camoufox/`. Do not vendor upstream tests back into it — a deliberate difference
from upstream belongs in `ci/skiplist.yml` with a stated reason.

`ccache` is enabled in the build config — install it for fast incremental rebuilds (cold ~40 min, incremental ~5 min).

## Constraints when editing this repo

- The `camoufox-*/` source directory is regenerated — persist changes as patches, never as edits committed to that tree.
- Keep the `Makefile` diff clean against `main` unless a change genuinely belongs there — dependency setup lives in `scripts/install-deps.sh`, not the Makefile.
- Every PR must be tied to a GitHub issue and pass the full pipeline (see `CONTRIBUTING.md` and `ci/README.md`).
