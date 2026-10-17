"""
Verify no OS font base claims a page into a multi-second stall.

A base in font-bases.json is a list of family names the browser claims. Several
names can name the same physical face -- macOS exposes its UI font under a
localized name per language, and all of them live in that font's `name` table --
and the masked font list hands each one to the browser as a family of its own.

Font fallback walks that list once per codepoint the page's own fonts do not
cover, so a face reached by N names is loaded and scanned N times per miss. The
sonoma base named 30 families that all resolve to 42__SFNS.ttf, which is one
~1 MB face covering no emoji, against one name in tahoe26 and macos27. On an
emoji-heavy page that cost the content process about 20 s inside one reflow,
during which the page answered nothing (daijro/camoufox#832). The stall is also
a tell in itself: no stock Firefox freezes on an emoji page, and a script can
time it.

The probe asks the page for an aria snapshot twice a second for a bounded
window and measures the longest UNBROKEN run of slow answers. A single slow
answer is not the defect and is not enough to fail: a healthy base on a busy
machine still spikes to a few hundred milliseconds, while the defect is a
continuous multi-second block during which nothing comes back at all.

What PASS means: no macOS base leaves the page unresponsive for a continuous
STALL_S or longer.

    python browser/tests/playwright/patches/system-font-alias-stall.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

CAMOUFOX = Path(__file__).resolve().parents[4] / "python" / "src" / "camoufox"

# Emoji-heavy, so most of its text misses the claimed fonts and falls back.
URL = "https://badssl.com/"

WINDOW_S = 30.0        # the stall starts ~5 s in and runs ~20 s
PROBE_EVERY_S = 0.5
PROBE_TIMEOUT_MS = 6000  # a cap, not the verdict: above it the page gave nothing
SLOW_MS = 1000           # a healthy base's worst answer measured ~740 ms
STALL_S = 5.0            # continuous unresponsiveness that no load noise makes


def base_lists(os_key: str = "mac"):
    """Each base's claimed font list, built the way a launch builds it."""
    bases = json.loads((CAMOUFOX / "font-bases.json").read_text())[os_key]
    essential = json.loads((CAMOUFOX / "essential-fonts.json").read_text())[os_key]
    return [(b["id"], sorted(set(b["fonts"]) | set(essential))) for b in bases]


async def longest_stall(fonts):
    """The longest continuous span of slow answers, and where it started.

    Span, not peak: the defect holds the content process inside one reflow, so
    every probe in that span is slow. Scattered spikes from an unrelated load
    do not accumulate into a span.
    """
    from camoufox.async_api import AsyncCamoufox

    longest, longest_at = 0.0, 0.0
    span_from = None
    worst = 0.0
    async with AsyncCamoufox(**launch_kwargs(os="macos", fonts=fonts)) as browser:
        page = await (await browser.new_context()).new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        start = time.monotonic()
        while time.monotonic() - start < WINDOW_S:
            at = time.monotonic() - start
            began = time.monotonic()
            try:
                await page.locator("body").aria_snapshot(timeout=PROBE_TIMEOUT_MS)
            except Exception:
                pass
            took = time.monotonic() - began
            worst = max(worst, took)
            if took * 1000 >= SLOW_MS:
                span_from = at if span_from is None else span_from
                span = (at + took) - span_from
                if span > longest:
                    longest, longest_at = span, span_from
            else:
                span_from = None
            await asyncio.sleep(max(0.0, PROBE_EVERY_S - (time.monotonic() - began)))
    return longest, longest_at, worst


async def main():
    passed = True
    for base_id, fonts in base_lists():
        stall, stall_at, worst = await longest_stall(fonts)
        if stall >= STALL_S:
            passed = False
            print(f"  FAIL {base_id}: unresponsive for {stall:.1f}s from {stall_at:.1f}s in "
                  f"({len(fonts)} fonts claimed)")
        else:
            print(f"  ok {base_id}: no stall, worst answer {worst * 1000:.0f}ms "
                  f"({len(fonts)} fonts claimed)")
    if passed:
        print(f"  PASS: no macOS base went unresponsive for {STALL_S:.0f}s")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
