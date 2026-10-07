r"""
Verify launcher prefs are applied at STARTUP.

Playwright's non-persistent launch writes no user.js: firefox_user_prefs only
reach the browser through juggler's Browser.enable, after startup. Anything Gecko
reads while starting up raced or never applied -- intl.locale.requested lost the
race against the parent's pre-created dom.properties bundle on Windows
(fr-FR validation messages English in 3 of 4 launches), and mirror-once prefs
were ignored. pythonlib now also passes the prefs as CAMOU_PREFS_1..N and
settings/camoufox.cfg (autoconfig, evaluated before any service reads prefs)
applies them.

The guard passes a page-visible pref ONLY through CAMOU_PREFS_1 (not through
firefox_user_prefs, so juggler never sets it): dom.gamepad.enabled=false removes
navigator.getGamepads ([Pref="dom.gamepad.enabled"]). A control launch without
it must still expose getGamepads, so the check is not vacuous.

    python browser/tests/playwright/patches/startup-prefs.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402


def gamepads_type(binary: Path, env=None) -> str:
    from camoufox.sync_api import Camoufox
    with Camoufox(headless=True, executable_path=str(binary), env=env or {}, i_know_what_im_doing=True) as b:
        page = b.new_page()
        page.goto("about:blank")
        return page.evaluate("typeof navigator.getGamepads")


def main() -> int:
    binary = resolve_binary()
    control = gamepads_type(binary)
    applied = gamepads_type(binary, env={"CAMOU_PREFS_1": json.dumps({"dom.gamepad.enabled": False})})
    print(f"  control launch        : typeof navigator.getGamepads = {control}")
    print(f"  CAMOU_PREFS_1 applied : typeof navigator.getGamepads = {applied}")
    failures = []
    if control != "function":
        failures.append(f"control launch: getGamepads is {control} (expected function) -- check is vacuous")
    if applied != "undefined":
        failures.append("a pref passed via CAMOU_PREFS was not applied at startup (camoufox.cfg block missing?)")
    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: CAMOU_PREFS reaches camoufox.cfg at startup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
