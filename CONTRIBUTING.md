# Contributing to Camoufox

Thanks for your interest in contributing! Here's how to get started.

## Ways to Contribute

- **Bug reports** — Open an issue with steps to reproduce, expected behavior, and actual behavior.
- **Feature requests** — Open an issue describing the use case and why it's useful.
- **Code contributions** — Fork the repo, make your changes, and open a pull request.
- **Documentation** — Fixes and improvements to docs are always welcome.

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

1. Each pull request must be associated with a Github issue
2. Follow the pull request template
3. Keep commits focused — one logical change per commit.
4. Open a PR with a clear description of what you changed and why.
5. All pull requests must pass both the **build-tester** and **service_tests** test suites before merging.

## Testing Requirements

**Both test suites are required for every PR.** They test different layers of the stack and catch different classes of bugs — passing one does not substitute for the other.

### build-tester

Tests the **raw binary** in isolation, bypassing the Python package entirely. Fingerprints are injected manually via `generate_context_fingerprint` + `addInitScript` (per-context mode) and via the `CAMOU_CONFIG` environment variable (global mode). It also validates that injected values actually appear in the page via match result checks.

**Run this when you change:** browser patches, Firefox source modifications, WebGL/canvas/audio spoofing, WebRTC IP handling, or anything in the C++/JS browser layer.

```bash
cd build-tester
npm install          # first time only
pip install -r requirements.txt
python scripts/run_tests.py /path/to/camoufox-binary
```

See [`build-tester/README.md`](build-tester/README.md) for full details.

---

### service_tests

Tests the **full stack** — the binary and the Python package together — using only the public `AsyncNewContext` API. Fingerprints are generated entirely by camoufox/browserforge with no manual injection. Real proxies are required; the WebRTC IP and timezone are auto-derived from each proxy's exit IP. This is a black-box trust test: if it fails, the fix belongs in the Python package, not in the test.

**Run this when you change:** `pythonlib/` (fingerprint generation, `AsyncNewContext`, `NewContext`), proxy handling, or any behaviour that affects how the Python package interacts with the binary.

```bash
cd service_tests
# Add proxies (one per line, format: user:pass@domain:port)
cp proxies.txt.example proxies.txt   # or create manually
./run_tests.sh
```

See [`service_tests/README.md`](service_tests/README.md) for full details.

---

### Key differences

| | build-tester | service_tests |
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
- OS and Python version
- A minimal reproducible example

## Questions

For usage questions, check the [documentation](https://camoufox.com) first. For anything else, open an issue.
