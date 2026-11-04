r"""
Every screen coordinate a page can read agrees with the spoofed window.screenX/Y.

window.screenX/Y report the identity's position, but mozInnerScreenX/Y and the
screenX/Y of mouse and touch events were computed from the real window. Wherever
the real window is not at the spoofed position (any X11 desktop that places it,
a second monitor), the page could read the real position and see that

    mozInnerScreenY - screenY

is larger than the whole window's chrome. Stock places the content area inside
the window, and an event's screenX - clientX equals mozInnerScreenX. An event the
page constructs keeps the screen point it was given.

The spoofed position here is one the real window is not at: on the guard's
private Xvfb display, with no window manager, the window opens at the origin.

    python browser/tests/playwright/patches/window-screen-origin.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, launch_kwargs  # noqa: E402

# Setting any window.* key leaves the window's geometry to the caller (the
# launcher no longer fits the drawn window to the display), so the size is set
# too, inside the guard's 1400x900 display.
SPOOFED = {"window.screenX": 300, "window.screenY": 200,
           "window.outerWidth": 1000, "window.outerHeight": 650}

PAGE = """<body style="margin:0"><div style="width:400px;height:300px"></div><script>
const geometry = () => ({screenX, screenY, mozInnerScreenX, mozInnerScreenY,
                         outerWidth, outerHeight, innerWidth, innerHeight});
addEventListener('mousedown', e => {
  const made = new MouseEvent('mousedown', {screenX: 5, screenY: 7});
  document.body.dataset.result = JSON.stringify({geometry: geometry(),
    event: {screenX: e.screenX, screenY: e.screenY, clientX: e.clientX, clientY: e.clientY},
    constructed: [made.screenX, made.screenY]});
});
</script></body>"""


def probe() -> dict:
    from camoufox.sync_api import Camoufox

    with hidden_display(), Camoufox(**launch_kwargs(headless=False, os="windows",
                                                    config=SPOOFED,
                                                    i_know_what_im_doing=True)) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.mouse.click(120, 80)
        page.wait_for_function("document.body.dataset.result")
        return json.loads(page.get_attribute("body", "data-result"))


def main() -> int:
    result = probe()
    g, e = result["geometry"], result["event"]
    print(json.dumps(result))
    failures = []
    if (g["screenX"], g["screenY"]) != (SPOOFED["window.screenX"], SPOOFED["window.screenY"]):
        failures.append(f"screenX/Y are {g['screenX']},{g['screenY']}, not the spoofed "
                        f"position, so the check proves nothing")
    for axis, outer, inner in (("X", "outerWidth", "innerWidth"), ("Y", "outerHeight", "innerHeight")):
        offset = g[f"mozInnerScreen{axis}"] - g[f"screen{axis}"]
        chrome = g[outer] - g[inner]
        if not 0 <= offset <= chrome:
            failures.append(f"mozInnerScreen{axis} - screen{axis} = {offset}, outside the "
                            f"window's {chrome}px of chrome")
        client = e[f"client{axis}"]
        if abs(e[f"screen{axis}"] - client - g[f"mozInnerScreen{axis}"]) > 1:
            failures.append(f"event screen{axis} - client{axis} = {e[f'screen{axis}'] - client}, "
                            f"but mozInnerScreen{axis} = {g[f'mozInnerScreen{axis}']}")
    if result["constructed"] != [5, 7]:
        failures.append(f"new MouseEvent({{screenX: 5, screenY: 7}}) reads {result['constructed']}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: mozInnerScreenX/Y and event screen coordinates follow the spoofed window position")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
