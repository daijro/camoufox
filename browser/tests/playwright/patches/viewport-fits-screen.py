r"""
A viewport the caller asks for must fit on the screen the page sees.

Playwright's viewport= sizes the page, not the window, and nothing checked it
against the screen the identity claims. humanize-seam.py asked for a 1000x700
viewport on a launch that drew a 1366x768 screen: the page read innerHeight
700 with screen.availHeight 768, while a real Firefox window draws its toolbars
(86 px here) above the page. innerHeight + chrome > availHeight is a machine
that cannot exist, and fpgen's recorded 1366x768 Firefox windows never show a
page taller than 683 px.

The launcher now gives such a context a recorded screen that holds the
viewport in the recorded chrome (python/tests/test_viewport_fit.py), through
the per-context screen setter, and draws a persistent launch around the
viewport it is given. The guard launches identities on a small drawn screen
and asks for a viewport too tall for it:

  - the control, a page with no viewport: its outerHeight - innerHeight is the
    chrome this build draws, which must be non-zero, and the drawn screen must
    be too short for the viewport plus that chrome, or the check is vacuous;
  - new_page(viewport=), new_context(viewport=) and NewContext(viewport=):
    innerHeight + chrome <= screen.availHeight, innerWidth <= availWidth, and
    the page still has the viewport the caller asked for;
  - launch_persistent_context(viewport=): the same, and the window around the
    page is the viewport in the recorded chrome, on the screen.

Pages are loaded from a data: URL: the per-context setters run from init
scripts, which a context's first about:blank never gets (as in stock
Playwright).

    python browser/tests/playwright/patches/viewport-fits-screen.py
"""

import sys
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

VIEWPORT = {"width": 1000, "height": 700}
SMALL = {"max_width": 1366, "max_height": 768}
PAGE = "data:text/html,<p>viewport"

MEASURE = """() => ({
  screen: [screen.width, screen.height], avail: [screen.availWidth, screen.availHeight],
  outer: [outerWidth, outerHeight], inner: [innerWidth, innerHeight],
})"""


def measure(page) -> dict:
    page.goto(PAGE)
    return page.evaluate(MEASURE)


def fits(name: str, seen: dict, chrome: int) -> list:
    """innerHeight + chrome <= availHeight and innerWidth <= availWidth, at the
    viewport the caller asked for."""
    failures = []
    (iw, ih), (aw, ah) = seen["inner"], seen["avail"]
    if [iw, ih] != [VIEWPORT["width"], VIEWPORT["height"]]:
        failures.append(f"{name}: the page is {iw}x{ih}, not the {VIEWPORT} the caller asked for")
    if ih + chrome > ah:
        failures.append(f"{name}: innerHeight {ih} + {chrome} px of chrome > screen.availHeight {ah} ({seen})")
    if iw > aw:
        failures.append(f"{name}: innerWidth {iw} > screen.availWidth {aw} ({seen})")
    return failures


def check(os_name: str, binary) -> list:
    from camoufox import fingerprints
    from camoufox.fingerprints import Screen
    from camoufox.sync_api import Camoufox, NewContext

    # The recorded chrome a window has around its page (launcher-constants.json
    # recordedWindowChrome); a launcher from before it has none, and fails below.
    recorded_chrome = getattr(fingerprints, "RECORDED_WINDOW_CHROME", {"win": [18, 130], "mac": [0, 86], "lin": [2, 86]})

    seen = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Camoufox(os=os_name, headless=True, executable_path=str(binary), screen=Screen(**SMALL),
                      i_know_what_im_doing=True) as browser:
            seen["launch page"] = measure(browser.new_page())
            seen["new_page(viewport=)"] = measure(browser.new_page(viewport=VIEWPORT))
            seen["new_context(viewport=)"] = measure(browser.new_context(viewport=VIEWPORT).new_page())
            seen["NewContext(viewport=)"] = measure(NewContext(browser, os=os_name, viewport=VIEWPORT).new_page())
        with tempfile.TemporaryDirectory() as profile:
            with Camoufox(os=os_name, headless=True, executable_path=str(binary), persistent_context=True,
                          user_data_dir=profile, viewport=VIEWPORT, i_know_what_im_doing=True) as context:
                seen["persistent(viewport=)"] = measure(context.new_page())

    print(f"{os_name} identity:")
    for name, values in seen.items():
        print(f"  {name:24} {values}")
    for w in caught:
        print(f"  warning: {str(w.message).splitlines()[0][:160]}")

    control = seen.pop("launch page")
    chrome = control["outer"][1] - control["inner"][1]
    failures = []
    if chrome <= 0:
        failures.append(f"the launch page shows no chrome ({control}): the check is vacuous")
    if control["avail"][1] >= VIEWPORT["height"] + chrome:
        failures.append(f"the drawn screen {control['avail']} holds the viewport already: the check is vacuous")
    for name, values in seen.items():
        failures += fits(name, values, chrome)

    persistent = seen["persistent(viewport=)"]
    key = {"linux": "lin", "windows": "win", "macos": "mac"}[os_name]
    for axis, name in enumerate(("Width", "Height")):
        outer, inner, avail = persistent["outer"][axis], persistent["inner"][axis], persistent["avail"][axis]
        if not inner + recorded_chrome[key][axis] >= outer >= inner + (chrome if axis else 0):
            failures.append(f"persistent(viewport=): outer{name} {outer} is not the {inner} px page in its "
                            f"chrome ({persistent})")
        if outer > avail:
            failures.append(f"persistent(viewport=): outer{name} {outer} > screen.avail{name} {avail}")
    return [f"{os_name} identity: {f}" for f in failures]


def main() -> int:
    binary = resolve_binary()
    failures = []
    for os_name in ("linux", "windows"):
        failures += check(os_name, binary)

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: every page with a viewport fits on its screen with the browser's chrome around it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
