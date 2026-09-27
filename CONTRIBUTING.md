# Contributing to Camoufox

Thanks for your interest in contributing! Here's how to get started.

## Ways to Contribute

- **Bug reports** — Open an issue with steps to reproduce, expected behavior, and actual behavior.
- **Feature requests** — Open an issue describing the use case and why it's useful.
- **Code contributions** — Fork the repo, make your changes, and open a pull request.
- **Documentation** — Fixes and improvements to docs are always welcome.

Planned work is in [`ROADMAP.md`](ROADMAP.md). Comment on an item's issue before you start on it.

## Development Setup

See README.md for general setup. For iterative development with frequent rebuilds, install [ccache](https://ccache.dev/) to cache compiled objects:

```bash
# macOS
brew install ccache

# Linux
sudo apt install ccache   # Debian/Ubuntu
sudo dnf install ccache   # Fedora
```

ccache is already enabled in the build config. A cold build takes the usual ~40 minutes, but subsequent rebuilds drop to ~5 minutes for small changes.

## Pull Request Rules

The engineering rules in [`AGENTS.md`](AGENTS.md) apply to every change, whether a person or an agent wrote it. They cover less code, no band-aids, no flakes, and docs that ship with the code.

1. Each pull request must be associated with a Github issue
2. Follow the pull request template
3. Keep commits focused — one logical change per commit.
4. Open a PR with a clear description of what you changed and why.
5. All pull requests must pass the test pipeline before merging. It runs automatically — see below.

## Testing Requirements

**CI runs everything, on every pull request.** [`.github/workflows/tests.yml`](.github/workflows/tests.yml) builds the browser from your branch when you touch browser sources (and tests against the published release when you do not), then runs the Python and TypeScript package tests, the patch guards, build-tester, the upstream Playwright suite, the leak suite and the stealth check. Branch protection requires exactly one check, **`All tests passed`**, which is green only when every applicable suite is.

So there is nothing to attach to the pull request by hand. The old process — run the suites locally, screenshot the output, paste it in — was unenforceable: nothing checked that the browser in the screenshot was built from the branch under review. If you want a report in the description anyway, CI leaves one as a comment on the pull request.

[`ci/README.md`](ci/README.md) documents the pipeline: what each tier runs, what is deliberately skipped and why, and how to reproduce any gate locally against your own build:

```bash
python3 -m ci.run_patch_guards   --binary /path/to/camoufox-bin
python3 -m ci.run_build_tester   --binary /path/to/camoufox-bin
python3 -m ci.run_playwright     --binary /path/to/camoufox-bin   # or --shard 3/6
python3 -m ci.run_skiplist_audit --binary /path/to/camoufox-bin
python3 -m ci.run_pythonlib                                       # pythonlib/
python3 -m ci.run_typescript                                      # typescript/
python3 -m pytest ci/tests -q                                     # the pipeline's own tests
```

The two suites below are the ones worth running by hand while you work, because they are the ones that tell you quickly whether a spoofing change did what you meant. They test different layers and catch different classes of bug — passing one does not substitute for the other.

### build-tester

Tests the **raw binary** in isolation, bypassing the Python package entirely. Fingerprints are injected manually via `generate_context_fingerprint` + `addInitScript` (per-context mode) and via the `CAMOU_CONFIG` environment variable (global mode). It also validates that injected values actually appear in the page via match result checks.

**Run this when you change:** browser patches, Firefox source modifications, WebGL/canvas/audio spoofing, WebRTC IP handling, or anything in the C++/JS browser layer.

```bash
cd build-tester
npm install          # first time only
pip install -r requirements.txt
python scripts/run_tests.py /path/to/camoufox-binary
```

Or `python3 -m ci.run_build_tester --binary /path/to/camoufox-bin`, which is what CI runs — same suite, graded per check.

See [`build-tester/README.md`](build-tester/README.md) for full details.

---

### service-tester

Tests the **full stack** — the binary and the Python package together — using only the public `AsyncNewContext` API. Fingerprints are generated entirely by camoufox/fpgen with no manual injection. Real proxies are required; the WebRTC IP and timezone are auto-derived from each proxy's exit IP. This is a black-box trust test: if it fails, the fix belongs in the Python package, not in the test.

**Run this when you change:** `pythonlib/` (fingerprint generation, `AsyncNewContext`, `NewContext`), proxy handling, or any behaviour that affects how the Python package interacts with the binary.

```bash
cd service-tester
# Create proxies.txt: one user:pass@domain:port per line (# comments allowed)
./run_tests.sh
```

See [`service-tester/README.md`](service-tester/README.md) for full details.

---

### Key differences

| | build-tester | service-tester |
|---|---|---|
| Entry point | Raw binary path | `pip install camoufox` |
| Fingerprint injection | Manual | Via `AsyncNewContext` API |
| Global mode (`CAMOU_CONFIG`) | ✓ | ✗ |
| Match result validation | ✓ | ✗ |
| Proxy required | ✗ | ✓ |
| Profiles | 8 (6 per-context + 2 global) | 6 (per-context) |
| Fix target on failure | Browser source | Python package |

## Reporting Issues

Please search existing issues before opening a new one. Include:
- Camoufox version
- OS, and your Python or Node version
- A minimal reproducible example

## Questions

For usage questions, check the [documentation](https://camoufox.com) first. For anything else, open an issue.
