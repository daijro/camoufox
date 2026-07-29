"""
Verify humanize=True produces a native cursor trajectory (daijro/camoufox#677).

Camoufox's cursor humanization has a single call site: the `mousemove` branch of
`sendEvents()` in additions/juggler/protocol/PageHandler.js, which calls
`ChromeUtils.camouGetMouseTrajectory(...)` and dispatches the intermediate
points. The Firefox 146 Juggler migration (commit 03c1230) rewrote that helper
and silently dropped the branch, so from FF146 through v152 `humanize=True`
emitted only the endpoint mousemove -- no trajectory at all.

This is runtime-only: the C++ generator (MouseTrajectories.hpp), the ChromeUtils
bindings, and the config plumbing all stay intact and every patch applies
cleanly, so nothing fails loudly. Only driving a real browser and counting the
emitted mousemove events catches it.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/humanize-mouse-trajectory.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * humanize=True expands one long mouse.move into many intermediate
      mousemove events, ending exactly on the requested destination;
    * a humanized click still lands on the target element;
    * without humanize, each move emits only its endpoint (pins the other
      direction so accidental always-on humanization is also caught).
"""

import asyncio
import os
import sys

from camoufox.async_api import AsyncCamoufox

DEST = (1100, 650)
BODY = '<body style="margin:0;width:1400px;height:800px"></body>'
RECORDER = """
    window.moves = [];
    addEventListener("mousemove", e => moves.push([e.clientX, e.clientY]));
"""

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")


def _launch_kwargs(humanize):
    kwargs = dict(headless=True, os="linux", humanize=humanize)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


async def _collect_moves(humanize):
    async with AsyncCamoufox(**_launch_kwargs(humanize)) as browser:
        page = await browser.new_page()
        await page.set_content(BODY)
        await page.evaluate(RECORDER)
        await page.mouse.move(20, 20)
        await page.mouse.move(*DEST)
        return await page.evaluate("moves")


async def _humanized_click_hits_target():
    async with AsyncCamoufox(**_launch_kwargs(True)) as browser:
        page = await browser.new_page()
        await page.set_content(
            '<button id="b" style="position:absolute;left:600px;top:400px">go</button>'
        )
        await page.evaluate(
            "window.moves=0;window.clicked=false;"
            "addEventListener('mousemove',()=>moves++);"
            "document.getElementById('b').addEventListener('click',()=>clicked=true)"
        )
        await page.click("#b")
        return await page.evaluate("moves"), await page.evaluate("clicked")


async def main() -> int:
    passed = True

    humanized = await _collect_moves(True)
    print("\n=== humanize=True ===")
    print(f"  mousemove events: {len(humanized)}  (endpoint: {humanized[-1] if humanized else None})")
    if len(humanized) >= 10 and humanized[-1] == list(DEST):
        print("  PASS: humanized trajectory emitted, ending on destination")
    else:
        passed = False
        print("  FAIL: expected >=10 intermediate points ending exactly on the destination")

    plain = await _collect_moves(False)
    print("\n=== humanize off ===")
    print(f"  mousemove events: {plain}")
    if plain == [[20, 20], list(DEST)]:
        print("  PASS: only endpoints emitted")
    else:
        passed = False
        print("  FAIL: expected only the two endpoints")

    moves, clicked = await _humanized_click_hits_target()
    print("\n=== humanized click ===")
    print(f"  intermediate moves: {moves}  clicked: {clicked}")
    if moves >= 10 and clicked:
        print("  PASS: humanized click landed on the target")
    else:
        passed = False
        print("  FAIL: humanized click did not humanize or missed the target")

    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
