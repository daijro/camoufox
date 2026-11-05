"""
A driver's click holds the button as long as a person's does.

Playwright clicks with mousedown and mouseup back to back (click(), dblclick(),
mouse.click() without `delay`), so the page saw the button released under
10 ms after it was pressed, every time, on every Playwright variant (humanize
too), where a person's click on stock Firefox 158.0.1 Linux is held tens of
milliseconds (under 250 ms, XTest on Xvfb). Juggler now holds it for a normal
draw around 110 ms (SD 30), never under 50 ms: a button is released no sooner
than that after it went down (PageHandler.js clickHold), and a script's own
longer `delay` stands as it is.

    python browser/tests/playwright/patches/driven-click-hold.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGE = '<!doctype html><html><body><button id="b" style="width:120px;height:40px">b</button></body></html>'
RECORD = """() => {
  window.__ev = [];
  for (const t of ['mousedown', 'mouseup']) {
    document.getElementById('b').addEventListener(t, (e) => window.__ev.push([t, e.timeStamp]));
  }
}"""


def holds(events):
    out, down = [], None
    for t, ts in events:
        if t == "mousedown":
            down = ts
        elif t == "mouseup" and down is not None:
            out.append(round(ts - down, 1))
            down = None
    return out


def probe(binary):
    from camoufox.sync_api import Camoufox

    results = {}
    with Camoufox(executable_path=str(binary), headless=True, os="linux", i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        box = page.locator("#b").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        for name, act in (("locator.click", lambda: page.locator("#b").click()),
                          ("mouse.click", lambda: page.mouse.click(cx, cy)),
                          ("dblclick", lambda: page.locator("#b").dblclick()),
                          ("click delay=400", lambda: page.locator("#b").click(delay=400))):
            page.evaluate(RECORD)
            act()
            page.wait_for_timeout(100)
            results[name] = holds(page.evaluate("window.__ev"))
    return results


def main() -> int:
    results = probe(resolve_binary())
    failures = []
    for name, hs in results.items():
        # A person's hold has no ceiling (PageHandler.js clickHold), only its floor.
        want = (380, 600) if "delay=400" in name else (45, float("inf"))
        if not hs or min(hs) < want[0] or max(hs) > want[1]:
            failures.append(f"{name}: button held {hs} ms, want {want[0]}-{want[1]}")
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"PASS: clicks are held as a person's are: {results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
