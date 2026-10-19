"""
Verify the browser logs nothing of its own unless the `debug` config key is set.

ChromeUtils.camouDebug() writes to stderr. Its callers pass page-derived text:
Juggler logs the body of every `mw:` evaluation, and the window module logs the
addons and certificates it installs. It used to log whenever `debug` was absent,
which is every normal launch, because it only stayed quiet for an explicit
`debug: False`.

What PASS means:
    * by default, an `mw:` evaluation leaves no trace on the browser's stderr;
    * with config {"debug": True}, the same evaluation is logged, so the probe
      really reaches the logging call.

    python browser/tests/playwright/patches/debug-logging-off.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

MARKER = "camoufox-debug-probe-7f3c"
TIMEOUT_S = 180


def probe(config: dict) -> None:
    from camoufox.sync_api import Camoufox

    with Camoufox(headless=True, os="linux", config=config, main_world_eval=True,
                  i_know_what_im_doing=True,
                  executable_path=str(resolve_binary())) as browser:
        page = browser.new_page()
        page.evaluate(f"mw:'{MARKER}'.length")


def browser_stderr(config: dict) -> str:
    """Run the probe in a child whose Playwright driver echoes the browser's stderr."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe", json.dumps(config)],
        capture_output=True, text=True, timeout=TIMEOUT_S,
        env={**os.environ, "DEBUG": "pw:browser"},
    )
    if proc.returncode != 0:
        raise SystemExit(f"probe failed:\n{proc.stderr[-2000:]}")
    return proc.stderr


def main() -> int:
    passed = True
    for config, expect_logged in (({}, False), ({"debug": True}, True)):
        label = "debug=True" if config else "default"
        logged = MARKER in browser_stderr(config)
        if logged == expect_logged:
            print(f"  PASS {label}: mw: body {'logged' if logged else 'not logged'}")
        else:
            passed = False
            print(f"  FAIL {label}: mw: body {'logged' if logged else 'not logged'}, "
                  f"expected {'logged' if expect_logged else 'not logged'}")
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        probe(json.loads(sys.argv[2]))
        sys.exit(0)
    sys.exit(main())
