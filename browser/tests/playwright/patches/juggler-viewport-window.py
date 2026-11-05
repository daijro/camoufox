r"""
A page with a viewport sits inside its window, as in a real browser.

Playwright's viewport= sizes the page; Juggler (PageTarget.updateViewportSize)
then resizes the browser's window around it. CamoufoxWindow.sys.mjs held every
new window at the identity's outer size for its first five seconds and undid
that resize, so a context asking for a viewport larger than the launch window
got a page that overflowed its own window: innerHeight 700 in an outerHeight
699 window (measured on pkg-it3, a Windows identity on a 1366x768 draw). No
real window is smaller than the page it shows.

Now the hold gives way to the viewport, and Juggler sizes the window to the
viewport plus the chrome the claimed OS records (launcher-constants.json
recordedWindowChrome, which the launcher draws a screen around a viewport
with). For a Windows and a Linux identity, a viewport larger than the launch
window, set through new_context(viewport=), new_page(viewport=),
NewContext(viewport=) and set_viewport_size(), must read:

  - innerWidth/innerHeight = the viewport asked for;
  - outerWidth/outerHeight = the viewport plus the recorded chrome, so
    inner <= outer on both axes;
  - the window within the screen's available rect the page sees.

The control is the launch page: its window must be too small for the viewport,
or the check proves nothing. Measured in the first seconds of each window,
inside the startup hold.

    python browser/tests/playwright/patches/juggler-viewport-window.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

VIEWPORT = {"width": 1000, "height": 700}
RESIZED = {"width": 900, "height": 650}
PAGE = "data:text/html,<p>viewport"
CONSTANTS = Path(__file__).resolve().parents[4] / "python" / "src" / "camoufox" / "launcher-constants.json"

MEASURE = """() => ({
  inner: [innerWidth, innerHeight], outer: [outerWidth, outerHeight], at: [screenX, screenY],
  avail: [screen.availLeft, screen.availTop, screen.availWidth, screen.availHeight],
})"""


def measure(page) -> dict:
    page.goto(PAGE)
    return page.evaluate(MEASURE)


def judge(name: str, seen: dict, viewport: dict, chrome: list) -> list:
    failures = []
    want_inner = [viewport["width"], viewport["height"]]
    want_outer = [want_inner[0] + chrome[0], want_inner[1] + chrome[1]]
    if seen["inner"] != want_inner:
        failures.append(f"{name}: the page is {seen['inner']}, not the {want_inner} asked for ({seen})")
    for axis, label in enumerate(("Width", "Height")):
        if seen["inner"][axis] > seen["outer"][axis]:
            failures.append(f"{name}: inner{label} {seen['inner'][axis]} > outer{label} {seen['outer'][axis]} ({seen})")
    if seen["outer"] != want_outer:
        failures.append(f"{name}: the window is {seen['outer']}, not the viewport in the recorded chrome "
                        f"{chrome}: {want_outer} ({seen})")
    left, top, width, height = seen["avail"]
    x, y = seen["at"]
    if x < left or y < top or x + seen["outer"][0] > left + width or y + seen["outer"][1] > top + height:
        failures.append(f"{name}: the window {seen['at']}+{seen['outer']} is not within the available "
                        f"screen {seen['avail']}")
    return failures


def check(os_name: str, binary, headless) -> list:
    from camoufox.fingerprints import Screen
    from camoufox.sync_api import Camoufox, NewContext

    key = {"linux": "lin", "windows": "win", "macos": "mac"}[os_name]
    chrome = json.loads(CONSTANTS.read_text())["recordedWindowChrome"][key]
    seen = {}
    with Camoufox(os=os_name, headless=headless, executable_path=str(binary),
                  screen=Screen(max_width=1366, max_height=768), i_know_what_im_doing=True) as browser:
        control = measure(browser.new_page())
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        seen["new_context(viewport=)"] = (measure(page), VIEWPORT)
        page.set_viewport_size(RESIZED)
        seen["set_viewport_size()"] = (page.evaluate(MEASURE), RESIZED)
        seen["new_page(viewport=)"] = (measure(browser.new_page(viewport=VIEWPORT)), VIEWPORT)
        seen["NewContext(viewport=)"] = (measure(NewContext(browser, os=os_name, viewport=VIEWPORT).new_page()), VIEWPORT)

    print(f"{os_name} identity (recorded chrome {chrome}):")
    print(f"  {'launch page':24} {control}")
    for name, (values, _) in seen.items():
        print(f"  {name:24} {values}")
    failures = []
    if control["outer"][1] >= VIEWPORT["height"] + chrome[1]:
        failures.append(f"the launch window {control['outer']} holds the viewport already: the check is vacuous")
    for name, (values, viewport) in seen.items():
        failures += judge(name, values, viewport, chrome)
    return [f"{os_name} identity: {f}" for f in failures]


def main() -> int:
    binary = resolve_binary()
    headless = "--headed" not in sys.argv
    failures = []
    for os_name in ("windows", "linux"):
        failures += check(os_name, binary, headless)
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: every page with a viewport sits inside a window the viewport plus the recorded chrome, on its screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
