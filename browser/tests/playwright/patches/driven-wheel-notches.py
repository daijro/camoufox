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
A line is the scroller's line height, so the 16 and 48 follow the page's font.

Juggler sent the requested pixels instead, unless humanize was on: deltaMode 0,
deltaY 100, wheelDeltaY -300, DOMMouseScroll detail 5, one event however far
the scroll. No wheel produces that, and a page reads it off the first event.

mouse.wheel(dx, dy) turns 100 px into one notch, rounding, at least one; the
notches of one call arrive tens of milliseconds apart. A long wheel leaves the
browser-wide activation slot free between them, so input in another context does
not wait for it to finish.

    python browser/tests/playwright/patches/driven-wheel-notches.py
"""

import asyncio
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


async def contended_wheel(binary):
    """Click in one context while another scrolls. The stamps are the wheel's."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=False, os="linux", window=(1280, 900)) as browser:
        pages = []
        for _ in range(2):
            page = await (await browser.new_context()).new_page()
            await page.set_content(PAGE)
            pages.append(page)
        scrolling, clicking = pages
        await scrolling.mouse.move(190, 140)
        await scrolling.evaluate(RECORD)
        wheel = asyncio.create_task(scrolling.mouse.wheel(0, 20000))
        await asyncio.sleep(0.3)
        await clicking.mouse.click(190, 140)
        finished_first = wheel.done()
        await wheel
        events = await scrolling.evaluate("window.__events")
        return finished_first, [e[5] for e in events if e[0] == "wheel"]


def mac_failures(got):
    failures = []
    line = next(e[1] for e in got["slow"][0] if e[0] == "MozMousePixelScroll")
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
        if not wheels or wheels[0] != 1 or sum(wheels) != lines:
            failures.append(f"macOS mouse.wheel ({name}) sent lines {wheels}: a burst starts at 1 and totals {lines}")
        if scrolled != line * lines:
            failures.append(f"macOS mouse.wheel ({name}) scrolled {scrolled} px, expected {line * lines}")
    return failures


def main() -> int:
    with hidden_display("1920x1080"):
        binary = resolve_binary()
        got = probe(binary, "linux", (("one", 100), ("three", 300)))
        mac = probe(binary, "macos", (("slow", 16), ("turn", 100), ("long", 1000)))
        wheel_finished_first, contended = asyncio.run(contended_wheel(binary))
    failures = mac_failures(mac)
    if wheel_finished_first:
        failures.append("a click in another context waited for a long wheel to finish")
    if any(b - a < 10 for a, b in zip(contended, contended[1:])):
        failures.append("a click in another context bunched a long wheel's notches under 10 ms apart")
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
