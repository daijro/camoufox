r"""
A window a page opens gets the size and position its window.open() features
ask for, and every window reports its own content size; the window automation
opens reports the identity's position.

CamoufoxWindow.sys.mjs resizes a new browser window to the identity's outer
size and holds that size through startup. It did that to every window,
including one a page opened, so

    window.open('about:blank', '', 'width=400,height=300')

came back as large as the main window, where stock gives a 400x300 content area.
Only the windows automation opens are the identity's; a window with an opener
is sized as stock sizes it.

Position the same way: window.screenX/screenY answered the identity's
position for every window, so the popup below read the main window's
position instead of the left=37,top=41 it asked for. Now the first window is
moved to the identity's position and every window reports where it is.

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
PLACED = [37, 41]
CLAIMED = [123, 45]
# A screen and window the claimed position fits in: the launcher clamps a
# position that would put the window off the screen.
CONFIG = {
    "window.screenX": CLAIMED[0],
    "window.screenY": CLAIMED[1],
    "screen.width": 1920,
    "screen.height": 1080,
    "screen.availLeft": 0,
    "screen.availTop": 0,
    "screen.availWidth": 1920,
    "screen.availHeight": 1080,
    "window.innerWidth": 1366,
    "window.innerHeight": 643,
    "window.outerWidth": 1366,
    "window.outerHeight": 728,
}
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
        main_pos = await page.evaluate("() => [screenX, screenY]")
        frame_size = await page.evaluate(FRAME_SIZE)
        async with page.context.expect_page() as popup_info:
            await page.evaluate(
                f"() => {{ window.open('about:blank', '', "
                f"'width={REQUESTED[0]},height={REQUESTED[1]},"
                f"left={PLACED[0]},top={PLACED[1]}'); }}"
            )
        popup = await popup_info.value
        await popup.wait_for_load_state()
        readings, positions = [], []
        for _ in range(6):
            readings.append(await popup.evaluate("() => [innerWidth, innerHeight]"))
            positions.append(await popup.evaluate("() => [screenX, screenY]"))
            await asyncio.sleep(0.5)
        return main_size, main_pos, frame_size, readings, positions


def main() -> int:
    main_size, main_pos, frame_size, readings, positions = asyncio.run(probe(resolve_binary()))
    print(f"main window inner and outer {main_size} at {main_pos}, iframe inner {frame_size}, "
          f"popup inner {readings} at {positions}")
    failures = []
    if main_size[:2] != [CONFIG["window.innerWidth"], CONFIG["window.innerHeight"]]:
        failures.append(f"the main window's content area {main_size[:2]} is not the identity's")
    if main_size[2] == REQUESTED[0]:
        failures.append("the main window is the popup's width, so the check proves nothing")
    if frame_size != FRAME:
        failures.append(f"a {FRAME} iframe reports {frame_size}")
    if any(reading != REQUESTED for reading in readings):
        failures.append(f"the popup's content area is not the {REQUESTED} its features asked for")
    if main_pos != CLAIMED:
        failures.append(f"the main window is not at the identity's position {CLAIMED}")
    if any(position != PLACED for position in positions):
        failures.append(f"the popup does not report the position {PLACED} its features asked for")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a page's popup keeps its requested size and position, and an iframe its own size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
