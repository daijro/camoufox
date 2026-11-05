"""
mouse.wheel() reaches the page as a mouse wheel does in stock Firefox.

A wheel turns in notches. On Linux (GTK, X11) stock Firefox 158.0.1 delivers
each notch as its own `wheel` event: deltaMode 1 (lines), deltaY 6,
wheelDeltaY -120, then DOMMouseScroll with detail 3 and MozMousePixelScroll
with detail 60 (three 20 px lines), and the scroller moves 120 px per notch.
Measured with XTest button 5 on Xvfb (three runs,
identical).

Juggler sent the requested pixels instead, unless humanize was on: deltaMode 0,
deltaY 100, wheelDeltaY -300, DOMMouseScroll detail 5, one event however far
the scroll. No wheel produces that, and a page reads it off the first event.

mouse.wheel(dx, dy) turns 100 px into one notch, rounding, at least one; the
notches of one call arrive tens of milliseconds apart.

    python browser/tests/playwright/patches/driven-wheel-notches.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:0;font:14px/18px sans-serif">
<div id="s" style="position:absolute;left:40px;top:40px;width:300px;height:200px;overflow:auto">
<div style="width:3000px;height:3000px"></div></div></body></html>"""
RECORD = """() => {
  window.__events = [];
  const s = document.getElementById('s');
  const on = (e) => window.__events.push(e.type === 'wheel'
    ? ['wheel', e.deltaMode, e.deltaX, e.deltaY, e.wheelDeltaY, Math.round(e.timeStamp)]
    : [e.type, e.detail]);
  for (const t of ['wheel', 'DOMMouseScroll', 'MozMousePixelScroll']) s.addEventListener(t, on);
}"""

# stock 158.0.1, GTK/X11, one notch
NOTCH = [["wheel", 1, 0, 6, -120], ["DOMMouseScroll", 3], ["MozMousePixelScroll", 60]]
NOTCH_PX = 120


def probe(binary):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os="linux", window=(1280, 900)) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.mouse.move(190, 140)
        page.evaluate(RECORD)
        out = {}
        for name, dy in (("one", 100), ("three", 300)):
            page.evaluate("() => { window.__events = []; document.getElementById('s').scrollTop = 0; }")
            page.mouse.wheel(0, dy)
            page.wait_for_timeout(800)
            out[name] = (page.evaluate("window.__events"), page.evaluate("document.getElementById('s').scrollTop"))
        return out


def main() -> int:
    with hidden_display("1920x1080"):
        got = probe(resolve_binary())
    failures = []
    for name, notches in (("one", 1), ("three", 3)):
        events, scrolled = got[name]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        if shape != NOTCH * notches:
            failures.append(f"mouse.wheel ({name}) delivered {shape}, stock {NOTCH * notches}")
        if scrolled != NOTCH_PX * notches:
            failures.append(f"mouse.wheel ({name}) scrolled {scrolled} px, stock {NOTCH_PX * notches}")
        stamps = [e[5] for e in events if e[0] == "wheel"]
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        if any(g < 10 for g in gaps):
            failures.append(f"mouse.wheel ({name}) notches {gaps} ms apart: no wheel turns that fast")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: mouse.wheel turns notches as a wheel does in stock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
