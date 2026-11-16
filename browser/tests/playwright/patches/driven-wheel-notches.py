"""
mouse.wheel() reaches the page as a mouse wheel does in stock Firefox.

A wheel turns in notches. On Linux (GTK, X11) stock Firefox 158.0.1 delivers
each notch as its own `wheel` event: deltaMode 1 (lines), deltaY 6,
wheelDeltaY -120, then DOMMouseScroll with detail 3 and MozMousePixelScroll
with detail 60 (three 20 px lines), and the scroller moves 120 px per notch.
Measured with XTest button 5 on Xvfb (three runs,
identical). docs/input-dispatch.md has the Windows measurement, which has the
same shape.

macOS differs. A person's notched mouse on stock 159.0 gives one line a slow
notch: deltaY 1, wheelDeltaY -48, DOMMouseScroll detail 1, MozMousePixelScroll
16. A faster turn starts at one line and grows, with those values in proportion.
A line is the scroller's line height, so the 16 and 48 follow the page's font;
the legacy events carry it rounded, the scroll moves the exact (at 2x, half-pixel) amount.

Juggler once sent the requested pixels instead: deltaMode 0, deltaY 100,
wheelDeltaY -300, DOMMouseScroll detail 5. No wheel produces that, and a page
reads it off the first event.

One mouse.wheel(dx, dy) call is one wheel event; the browser adds no pacing or
splitting of its own (a driver that wants a person's strokes sends one call per
notch, on its own schedule). On Linux and Windows 100 px is one notch, rounding,
at least one, and the notches of a call ride in that one event, as a
WM_MOUSEWHEEL of N x 120 (WinMouseScrollHandler) or a GTK smooth delta of N
does: deltaY 6 per notch, wheelDeltaY -120 per notch. On macOS the call is one
event of round(px / 16) lines.

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


def notched(n):
    """One event carrying n notches: each field is n times one notch's."""
    return [["wheel", 1, 0, 6 * n, -120 * n], ["DOMMouseScroll", 3 * n], ["MozMousePixelScroll", 60 * n]]


def probe(binary, os, turns):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os=os, window=(1280, 900)) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.mouse.move(190, 140)
        page.evaluate(RECORD)
        out = {}
        for name, dy in turns:
            page.evaluate("() => { window.__events = []; document.getElementById('s').scrollTop = 0; }")
            page.mouse.wheel(0, dy)
            page.wait_for_timeout(800)
            out[name] = (page.evaluate("window.__events"), page.evaluate("document.getElementById('s').scrollTop"))
        return out


def mac_failures(got):
    failures = []
    line = next(e[1] for e in got["slow"][0] if e[0] == "MozMousePixelScroll")
    # The scroller's line height, which a one-line notch scrolls. At a
    # devicePixelRatio of 2 it can be a half pixel (29 device px = 14.5 CSS
    # px): stock scrolls the fraction, while the legacy events carry it rounded
    # (EventStateManager: CSSIntSize::FromAppUnitsRounded, "We don't deal with
    # fractional amount in legacy event").
    line_px = got["slow"][1]
    if round(line_px + 1e-9) != line:
        failures.append(f"macOS line height {line_px} px, but MozMousePixelScroll carries {line}")
    for name, lines in (("slow", 1), ("turn", 6), ("long", 63)):
        events, scrolled = got[name]
        wheels = [e[3] for e in events if e[0] == "wheel"]
        expected = [
            part
            for dy in wheels
            for part in (["wheel", 1, 0, dy, -3 * line * dy], ["DOMMouseScroll", dy], ["MozMousePixelScroll", line * dy])
        ]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        if shape != expected:
            failures.append(f"macOS mouse.wheel ({name}) delivered {shape}, expected {expected}")
        if wheels != [lines]:
            failures.append(f"macOS mouse.wheel ({name}) sent lines {wheels}: one event of {lines} lines")
        if abs(scrolled - line_px * lines) > 0.01:
            failures.append(f"macOS mouse.wheel ({name}) scrolled {scrolled} px, expected {line_px * lines}")
    return failures


def main() -> int:
    with hidden_display("1920x1080"):
        binary = resolve_binary()
        got = probe(binary, "linux", (("one", 100), ("three", 300), ("short", 30)))
        mac = probe(binary, "macos", (("slow", 16), ("turn", 100), ("long", 1000)))
    failures = mac_failures(mac)
    for name, notches in (("one", 1), ("three", 3), ("short", 1)):
        events, scrolled = got[name]
        shape = [e[:5] if e[0] == "wheel" else e for e in events]
        if shape != notched(notches):
            failures.append(f"mouse.wheel ({name}) delivered {shape}, expected {notched(notches)}")
        if scrolled != NOTCH_PX * notches:
            failures.append(f"mouse.wheel ({name}) scrolled {scrolled} px, stock {NOTCH_PX * notches}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: one mouse.wheel call is one native wheel event")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
