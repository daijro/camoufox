# Camoufox Test Harness

Camoufox does **not** maintain its own copy of the Playwright Python
test suite. Instead, the runner pulls upstream tests from
[microsoft/playwright-python](https://github.com/microsoft/playwright-python)
at the tag matching the installed `playwright` package, and runs them
against the Camoufox binary. Camoufox-specific tests live in this
directory only.

## Quick start

```bash
# One-time setup
bash setup-venv.sh

# Run upstream Playwright suite against a Camoufox binary
./run-tests.sh --executable-path /path/to/camoufox

# Skip the upstream suite, only run Camoufox-specific tests
./run-tests.sh --executable-path /path/to/camoufox --camoufox-only
```

Add `--headful` to disable headless mode (requires a real X server or
xvfb-run); the default is headless.

## What runs

Three layers, in order:

1. **Upstream Playwright tests** — `microsoft/playwright-python` at
   the tag matching the installed `playwright` package. Cloned on
   first run into `.upstream-cache/v<version>/` (gitignored). These
   test the standard Playwright API surface: pages, frames, network,
   tracing, etc. They are the core "is this binary a working
   Firefox-with-Juggler?" check.

2. **Camoufox conftest plugin** — `conftest_camoufox.py` here.
   Loaded into the upstream pytest run as a plugin via
   `-p camoufox.conftest_camoufox`. Adds:
   - `executable_path` injection from `CAMOUFOX_EXECUTABLE_PATH`.
   - `xvfb_or_skip` autouse fixture that skips `headless=False`
     tests cleanly when there's no `DISPLAY`.
   - Stealth-aware fixtures (e.g. UA assertions accept `Camoufox/...`
     in addition to `Firefox/...`).

3. **Camoufox-only tests** — `test_*.py` here. These exercise things
   that *aren't* in upstream:
   - Stealth: launch arg vs. fingerprint conflicts (locale, UA,
     timezone), build-tester smoke as a pytest case.
   - xvfb / virtual display launching (the `headless="virtual"` path
     in `pythonlib/`).
   - Camoufox CLI flags and `CAMOU_CONFIG` env-var.

## Version resolution

The upstream tag is whatever the *installed* `playwright` package
reports as its version:

```python
import playwright
playwright.__version__   # → "1.59.0"
```

To bump:
1. Edit `local-requirements.txt` (e.g. `playwright==1.60.0`).
2. Re-run `setup-venv.sh`.
3. Re-run the suite. The runner will download
   `microsoft/playwright-python@v1.60.0` into a fresh cache directory.
4. Triage any new failures; if they're real Camoufox regressions add
   them to the per-version known-failures list (see below).

## Known failures (per upstream tag)

`known-failures-v<version>.txt` files in this directory list tests
that are expected to fail for a given upstream tag — typically real
Camoufox bugs we haven't fixed yet, or upstream tests that depend on
Chromium-only behaviour. The runner uses these as `--deselect`
arguments.

When a fix lands and a test goes green, *delete* its line from the
known-failures file rather than amending it. The list should only
shrink.

## Why we don't vendor

The previous approach (vendoring upstream `tests/` into
`camoufox/tests/async/`) caused two years of drift: assertions for
removed APIs (`Page.accessibility`), missing tests that lived
upstream (`test_check.py`, `test_click.py`, etc., which were
imported once and renamed `.disabled` when they failed), and
constant `playwright._impl._*` import breakage on every upstream
release. The version-pinned-clone approach gets all of that for free
in exchange for a one-time download per Playwright bump.
