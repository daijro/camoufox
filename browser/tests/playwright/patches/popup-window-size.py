r"""
A window a page opens gets the size its window.open() features ask for, and
every window reports its own content size.

CamoufoxWindow.sys.mjs resizes a new browser window to the identity's outer
size and holds that size through startup. It did that to every window,
including one a page opened, so

    window.open('about:blank', '', 'width=400,height=300')

came back as large as the main window, where stock gives a 400x300 content area.
Only the windows automation opens are the identity's; a window with an opener
is sized as stock sizes it.

innerWidth and innerHeight returned the identity's window.innerWidth and
innerHeight in every window, so that popup and every iframe reported the main
window's content size, larger than the popup's own outerWidth (#963). The
identity here carries both sizes, and a 300x150 iframe must report 300x150.

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
FRAME = [300, 150]
CONFIG = {"window.innerWidth": 1366, "window.innerHeight": 643,
          "window.outerWidth": 1366, "window.outerHeight": 728}
FRAME_SIZE = f"""() => new Promise(resolve => {{
  const frame = document.createElement('iframe');
  frame.style = 'border:0;width:{FRAME[0]}px;height:{FRAME[1]}px';
  frame.onload = () => resolve([frame.contentWindow.innerWidth, frame.contentWindow.innerHeight]);
  document.body.appendChild(frame);
}})"""


async def probe(binary):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, executable_path=str(binary), config=CONFIG,
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        main_size = await page.evaluate("() => [innerWidth, innerHeight, outerWidth, outerHeight]")
        frame_size = await page.evaluate(FRAME_SIZE)
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
        return main_size, frame_size, readings


def main() -> int:
    main_size, frame_size, readings = asyncio.run(probe(resolve_binary()))
    print(f"main window inner and outer {main_size}, iframe inner {frame_size}, popup inner {readings}")
    failures = []
    if main_size[:2] != [CONFIG["window.innerWidth"], CONFIG["window.innerHeight"]]:
        failures.append(f"the main window's content area {main_size[:2]} is not the identity's")
    if main_size[2] == REQUESTED[0]:
        failures.append("the main window is the popup's width, so the check proves nothing")
    if frame_size != FRAME:
        failures.append(f"a {FRAME} iframe reports {frame_size}")
    if any(reading != REQUESTED for reading in readings):
        failures.append(f"the popup's content area is not the {REQUESTED} its features asked for")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a page's popup keeps the size its window.open() features ask for, and an iframe its own")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
