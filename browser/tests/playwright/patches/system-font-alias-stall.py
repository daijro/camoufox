"""
Verify no macOS font base makes font fallback pay for one face many times.

A base in font-bases.json is a list of family names the browser claims. Several
names can name the same physical face -- macOS exposes its UI font under a
localized name per language, and all of them live in that font's `name` table --
and the masked font list hands each one to the browser as a family of its own.

Font fallback walks that list once per codepoint the page's own fonts do not
cover, and each name of the system face costs a load and scan of that ~1 MB
face (42__SFNS.ttf), which covers no emoji. The sonoma base named it 30 times,
against once in tahoe26 and macos27, so the reflow that follows the background
cmap load on an emoji page held the content process for about 20 s instead of
under one (daijro/camoufox#832). The stall is also a tell in itself: no stock
Firefox freezes on an emoji page, and a script can time it.

The page lays out a line of emoji and a sentinel in a script that only a claimed
Noto family covers, then runs a 50 ms timer and keeps its longest interval: the
time the content process gave the page nothing. The sentinel is resolved once
it stops measuring as .notdef, against a reference span of unassigned
codepoints with as many hex digits, so the same missing-glyph boxes. Fallback
can resolve it in the first layout instead of a later reflow -- a claimed OS's
own per-script fallback table names the sentinel's font directly -- so the
first forced layout is timed as one interval too: a stall lands there when
fallback runs synchronously. The verdict is a ratio against a control launch
that claims the system face exactly once, so it reads how many times a base
pays for that face and not how fast the runner is.

What PASS means: no macOS base blocks the page MAX_RATIO times as long as a
list that claims the system face once does.

    python browser/tests/playwright/patches/system-font-alias-stall.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

CAMOUFOX = Path(__file__).resolve().parents[4] / "python" / "src" / "camoufox"

ORIGIN = "https://camoufox.test/"
# The ratio counts the names fallback pays for the system face under. Measured
# 0.9-1.6 for every healthy base and 27-30 for sonoma before #832, idle or
# with every core busy, so the threshold sits about 4x from each. Where the
# claimed OS's fallback table resolves in the first layout, the cost grows with
# the claimed list instead: 2.7-3.5 healthy, 19 for the pre-#832 sonoma list.
MAX_RATIO = 6.0
# Only bounds the wait. A base that stalls past it fails like one that stalls less.
DEADLINE_MS = 120_000

# The emoji are badssl.com's section headings, the page #832 was found on.
PAGE = """<!doctype html><meta charset="utf-8"><body>
<p>&#x1F39B; &#x1F3AB; &#x1F39F; &#x1F5BC; &#x270F;&#xFE0F; &#x1F500; &#x1F511; &#x2194;&#xFE0F;
&#x1F50D; &#x2B06;&#xFE0F; &#x1F440; &#x274C; &#x2620;&#xFE0F; &#x1F6E0; &#x1F4CB;</p>
<span id="sentinel">&#x1E900;&#x1E901;</span>
<span id="notdef">&#x1E8FE;&#x1E8FF;</span>
<span id="system" style="font-family: 'System Font', monospace">mmmmmmmmmmlli10OQ@#</span>
<span id="mono" style="font-family: monospace">mmmmmmmmmmlli10OQ@#</span>
<script>
const width = id => document.getElementById(id).getBoundingClientRect().width;
const start = performance.now();
const notdef = width('notdef');
let last = performance.now(), longest = last - start;
(function tick() {
  const now = performance.now();
  longest = Math.max(longest, now - last);
  last = now;
  if (width('sentinel') === notdef) return setTimeout(tick, 50);
  document.documentElement.dataset.result = JSON.stringify({
    longest, resolvedAt: now - start, systemFont: width('system') !== width('mono'),
    sentinel: width('sentinel'), notdef,
  });
})();
</script>"""


def lists():
    """The control, then each macOS base's claimed list as a launch builds it.

    The control claims the system face once, next to the essential Noto
    families: enough families that fallback waits for their cmaps, as it does
    for a base, and none that names the system face again.
    """
    bases = json.loads((CAMOUFOX / "font-bases.json").read_text())["mac"]
    essential = json.loads((CAMOUFOX / "essential-fonts.json").read_text())["mac"]
    control = ["System Font"] + [f for f in essential if f.startswith("Noto ")]
    return [("control", control)] + [(b["id"], sorted(set(b["fonts"]) | set(essential))) for b in bases]


async def measure(fonts):
    """The page's longest unresponsive interval while fallback resolves, in ms."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(**launch_kwargs(os="macos", fonts=fonts, i_know_what_im_doing=True)) as browser:
        page = await browser.new_page()
        await page.route(ORIGIN, lambda route: route.fulfill(content_type="text/html", body=PAGE))
        await page.goto(ORIGIN)
        handle = await page.wait_for_function(
            "() => document.documentElement.dataset.result", timeout=DEADLINE_MS, polling=250
        )
        result = json.loads(await handle.json_value())
    if not result["systemFont"]:
        raise SystemExit("FAIL: 'System Font' is not installed, so nothing here pays for the "
                         "system face (is the font bundle staged?)")
    return result


async def main():
    failures = []
    control = None
    for name, fonts in lists():
        result = await measure(fonts)
        if control is None:
            control = result["longest"]
            print(f"  control: longest block {control:.0f}ms ({len(fonts)} fonts claimed, "
                  f"resolved at {result['resolvedAt']:.0f}ms)")
            continue
        ratio = result["longest"] / control
        verdict = "FAIL" if ratio >= MAX_RATIO else "ok"
        print(f"  {verdict} {name}: longest block {result['longest']:.0f}ms, {ratio:.1f}x the control "
              f"({len(fonts)} fonts claimed, resolved at {result['resolvedAt']:.0f}ms)")
        if ratio >= MAX_RATIO:
            failures.append(name)
    if failures:
        print(f"  FAIL: {', '.join(failures)} blocked the page {MAX_RATIO:.0f}x as long as the control")
        return 1
    print(f"  PASS: no macOS base blocked the page {MAX_RATIO:.0f}x as long as the control")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
