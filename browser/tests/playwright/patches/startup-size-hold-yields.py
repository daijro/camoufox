r"""
Fullscreen entered in the first seconds after launch fills the screen.

CamoufoxWindow.sys.mjs holds the window at the identity's size for five
seconds after launch, undoing the window manager's placement and maximize.
It answered every resize, so a page that went fullscreen in that window was
resized straight back out of it, and a find bar opened then made the window
grow instead of taking room from the content area. It also pinned the content
area to the identity's size for good, so even a fullscreen that stuck laid
the page out at the identity's size: innerWidth 1280 on a 1920 screen.
Stock gives the page the whole window, which in fullscreen is the screen
(the real one: headless, 1366x768).

Now the hold undoes only the window manager's changes and lets go in
fullscreen, and the pin comes off once the real content area is the
identity's.

    python browser/tests/playwright/patches/startup-size-hold-yields.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

SCREEN = [1920, 1080]
INNER = [1200, 700]


async def probe(binary):
    from camoufox.async_api import AsyncCamoufox

    config = {"screen.width": SCREEN[0], "screen.height": SCREEN[1],
              "screen.availWidth": SCREEN[0], "screen.availHeight": SCREEN[1],
              "window.innerWidth": INNER[0], "window.innerHeight": INNER[1]}
    async with AsyncCamoufox(headless=True, executable_path=str(binary), config=config,
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.set_content("<button onclick='document.documentElement.requestFullscreen()'>fs</button>")
        before = await page.evaluate("() => [innerWidth, innerHeight]")
        # Inside the five-second hold.
        await page.click("button")
        try:
            await page.wait_for_function("() => document.fullscreenElement", timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(1)
        during = await page.evaluate(
            "() => [innerWidth, innerHeight, outerWidth, outerHeight, !!document.fullscreenElement]")
        return before, during


def main() -> int:
    before, during = asyncio.run(probe(resolve_binary()))
    print(f"before {before}, in fullscreen {during}")
    failures = []
    if before != INNER:
        failures.append(f"the window did not start at the identity's {INNER}, so the check proves nothing")
    if not during[4]:
        failures.append("the page is not in fullscreen: the startup hold resized the window back")
    elif during[:2] != during[2:4] or during[:2] == INNER:
        failures.append(f"fullscreen lays the page out at {during[:2]}, not the whole window {during[2:4]}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: fullscreen entered during startup fills the screen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
