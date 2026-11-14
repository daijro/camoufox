r"""
Verify launcher prefs are applied at STARTUP, and that a pref which cannot be
applied stops the launch.

Playwright's non-persistent launch writes no user.js: firefox_user_prefs only
reach the browser through juggler's Browser.enable, after startup. Anything Gecko
reads while starting up raced or never applied -- intl.locale.requested lost the
race against the parent's pre-created dom.properties bundle on Windows
(fr-FR validation messages English in 3 of 4 launches), and mirror-once prefs
were ignored. The launchers therefore also pass the prefs as CAMOU_PREFS_1..N,
and browser/settings/camoufox.cfg (autoconfig, evaluated before any service
reads prefs) applies them.

The guard passes a page-visible pref ONLY through CAMOU_PREFS_1 (not through
firefox_user_prefs, so juggler never sets it): dom.gamepad.enabled=false removes
navigator.getGamepads ([Pref="dom.gamepad.enabled"]). A control launch without
it must still expose getGamepads, so the check is not vacuous.

A once-mirrored pref (`mirror: once` in StaticPrefList.yaml) keeps the value
it had when the first of them was read, so CAMOU_PREFS must be applied before
anything reads one. gfx.bundled-fonts.activate=0 through CAMOU_PREFS_1 must
stop a bare launch from rendering Twemoji Mozilla, the font Firefox bundles,
which a control launch renders. An unpackaged build fails this: autoconfig opens
prefcalls.js through a file channel, which starts the socket process and
freezes every once-mirrored pref before camoufox.cfg runs (daijro/camoufox#1050).

The loader used to return silently on JSON it could not parse and swallow each
pref that failed to set, so a launch ran on with identity prefs missing. Three
launches of the bare binary take a screenshot: unparseable JSON and a pref of
the wrong type must quit without it and name CAMOU_PREFS on stderr; a good pref
must still start normally.

    python browser/tests/playwright/patches/startup-prefs.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

TWEMOJI = """() => {
  const ctx = document.createElement('canvas').getContext('2d');
  const width = font => { ctx.font = font; return ctx.measureText('#0123456789').width; };
  return width('72px "Twemoji Mozilla", serif') !== width('72px serif');
}"""

LOADER_CASES = [
    ("unparseable JSON", '{"browser.startup.page":', False),
    ("a string for an integer pref", '{"browser.startup.page":"one"}', False),
    ("a valid pref", '{"browser.startup.page":1}', True),
]


def gamepads_type(binary: Path, env=None) -> str:
    from camoufox.sync_api import Camoufox
    # On top of the caller's environment: an env= replaces it whole.
    with Camoufox(headless=True, executable_path=str(binary), env={**os.environ, **(env or {})},
                  i_know_what_im_doing=True) as b:
        page = b.new_page()
        page.goto("about:blank")
        return page.evaluate("typeof navigator.getGamepads")


def twemoji_renders(binary: Path, prefs=None) -> bool:
    """Whether a bare launch, given `prefs` through CAMOU_PREFS_1, renders Twemoji Mozilla."""
    from playwright.sync_api import sync_playwright

    env = dict(os.environ)
    if prefs:
        env["CAMOU_PREFS_1"] = json.dumps(prefs)
    with sync_playwright() as p:
        browser = p.firefox.launch(executable_path=str(binary), headless=True, env=env)
        try:
            page = browser.new_page()
            return page.evaluate(TWEMOJI)
        finally:
            browser.close()


def bare_launch(binary: Path, prefs: str):
    """Whether a bare launch got as far as its screenshot (None if it hung), and its output."""
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "shot.png"
        try:
            proc = subprocess.run(
                [str(binary), "--headless", "--no-remote", "--profile", tmp,
                 "--screenshot", str(shot), "about:blank"],
                env=dict(os.environ, CAMOU_PREFS_1=prefs),
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return None, ""
        return shot.exists(), proc.stdout + proc.stderr


def main() -> int:
    binary = resolve_binary()
    failures = []

    control = gamepads_type(binary)
    applied = gamepads_type(binary, env={"CAMOU_PREFS_1": json.dumps({"dom.gamepad.enabled": False})})
    print(f"  control launch        : typeof navigator.getGamepads = {control}")
    print(f"  CAMOU_PREFS_1 applied : typeof navigator.getGamepads = {applied}")
    if control != "function":
        failures.append(f"control launch: getGamepads is {control} (expected function) -- check is vacuous")
    if applied != "undefined":
        failures.append("a pref passed via CAMOU_PREFS was not applied at startup (camoufox.cfg block missing?)")

    bundled = twemoji_renders(binary)
    once = twemoji_renders(binary, {"gfx.bundled-fonts.activate": 0})
    print(f"  control launch        : Twemoji Mozilla renders = {bundled}")
    print(f"  once-mirrored pref    : Twemoji Mozilla renders = {once} (gfx.bundled-fonts.activate=0)")
    if not bundled:
        failures.append("control launch: Twemoji Mozilla does not render -- check is vacuous")
    if once:
        failures.append("gfx.bundled-fonts.activate=0 via CAMOU_PREFS was not applied: "
                        "a once-mirrored pref was read before camoufox.cfg ran")

    for label, prefs, should_start in LOADER_CASES:
        started, output = bare_launch(binary, prefs)
        reported = "CAMOU_PREFS could not be applied" in output
        print(f"  {label}: started={started} reported={reported}")
        if started is None:
            failures.append(f"{label}: the browser hung at startup")
            continue
        if started != should_start:
            failures.append(f"{label}: the browser {'did not start' if should_start else 'started anyway'}")
        if reported == should_start:
            failures.append(f"{label}: stderr {'reported an error' if should_start else 'said nothing'}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: CAMOU_PREFS reaches camoufox.cfg at startup, and a pref it cannot apply stops the launch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
