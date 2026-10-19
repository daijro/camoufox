r"""
A window a page opens gets the size its window.open() features ask for.

CamoufoxWindow.sys.mjs resizes a new browser window to the identity's outer
size and holds that size through startup. It did that to every window,
including one a page opened, so

    window.open('about:blank', '', 'width=400,height=300')

came back as large as the main window, where stock gives a 400x300 content area.
Only the windows automation opens are the identity's; a window with an opener
is sized as stock sizes it.

The popup's size is read several times across the startup hold, so a late
resize to the identity's size is caught too.

    python browser/tests/playwright/patches/popup-window-size.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

REQUESTED = [400, 300]


async def probe(binary):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, executable_path=str(binary),
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        main_size = await page.evaluate("() => [outerWidth, outerHeight]")
        async with page.context.expect_page() as popup_info:
            await page.evaluate(
                f"() => {{ window.open('about:blank', '', "
                f"'width={REQUESTED[0]},height={REQUESTED[1]}'); }}"
            )
        popup = await popup_info.value
        await popup.wait_for_load_state()
        readings = []
        for _ in range(6):
            readings.append(await popup.evaluate("() => [innerWidth, innerHeight]"))
            await asyncio.sleep(0.5)
        return main_size, readings


def main() -> int:
    main_size, readings = asyncio.run(probe(resolve_binary()))
    print(f"main window outer {main_size}, popup inner {readings}")
    failures = []
    if main_size[0] == REQUESTED[0]:
        failures.append("the main window is the popup's width, so the check proves nothing")
    if any(reading != REQUESTED for reading in readings):
        failures.append(f"the popup's content area is not the {REQUESTED} its features asked for")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a page's popup keeps the size its window.open() features ask for")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
