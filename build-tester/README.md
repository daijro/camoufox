# Camoufox Build Tester

Tests a raw Camoufox binary (Firefox) directly against the same antibot-detection checks used in the service tests. Use this to validate a binary before packaging/releasing — it bypasses the Python package entirely.

## Prerequisites

- Python 3.9+
- Node.js (for building the TypeScript checks bundle via `esbuild`, first run only)

## Setup

```bash
# Install npm deps (once — needed to build the checks bundle)
npm install

# Install Python deps
pip install -r requirements.txt
```

## Usage

```bash
python scripts/run_tests.py <binary_path> [options]
```

**Example:**
```bash
python scripts/run_tests.py /path/to/camoufox-bin/camoufox
```

## Options

```
  binary_path           Path to the Camoufox (Firefox) binary
  --profile-count N     Number of profiles to test (1-8, default: 8)
  --secret KEY          HMAC signing key for certificate
  --save-cert PATH      Save certificate text to a file
  --no-cert             Skip certificate generation
```

## What It Tests

8 profiles total, run in two phases:

**Per-context phase (6 profiles)** — 3 macOS + 3 Linux profiles open simultaneously in a single browser instance, each with an isolated fingerprint injected via `addInitScript`. Tests that fingerprints are unique and don't leak between contexts.

**Global phase (2 profiles)** — 1 macOS + 1 Linux profile launched with fingerprint config passed via the `CAMOU_CONFIG` environment variable. Tests that browser-level fingerprint injection works correctly.

Each profile is scored across:

| Category | What it checks |
|---|---|
| Automation Detection | Playwright/CDP artefacts |
| JS Engine | V8 vs SpiderMonkey signals |
| Lie Detection | Inconsistent property overrides |
| Firefox APIs | Firefox-specific API presence |
| Cross-Signal | Consistency across navigator, screen, etc. |
| CSS Fingerprint | CSS rendering fingerprint |
| Canvas Noise | Canvas hash uniqueness and stability |
| WebGL Render | WebGL rendering hash |
| Audio Integrity | AudioContext fingerprint |
| Font Platform | OS-consistent font availability |
| Speech Voices | Voice list matches declared OS |
| WebRTC | IP spoofing (test IP injected) |
| Stability | Fingerprint stable over time |
| Headless Detection | No headless mode signals |
| Match Results | Injected values actually appear in page |

## How It Differs from the Service Tests

| | Build Tester | Service Tests |
|---|---|---|
| Entry point | Raw binary path | `pip install camoufox` |
| Fingerprint injection | Manual (`generate_context_fingerprint` + init script) | Via `AsyncNewContext` API |
| Global mode | Yes (`CAMOU_CONFIG` env var) | No |
| Match validation | Yes (checks injected values match page) | No |
| Proxy support | No | Yes |
| Profile count | 8 (6 per-context + 2 global) | 6 (per-context only) |

## The Checks Bundle

`scripts/checks-bundle.js` is a compiled artifact built from the TypeScript sources in `src/lib/checks/`. It is built automatically on first run. To force a rebuild, delete it:

```bash
rm scripts/checks-bundle.js
python scripts/run_tests.py <binary_path>
```

Source files:
- `src/lib/checks/index.ts` — entry point
- `src/lib/checks/core.ts` — automation, JS engine, lie detection, etc.
- `src/lib/checks/extended.ts` — canvas, WebGL, fonts, audio, etc.
- `src/lib/checks/workers.ts` — worker thread consistency
- `src/lib/checks/collectors.ts` — fingerprint data collectors (hashes, WebRTC, stability)
