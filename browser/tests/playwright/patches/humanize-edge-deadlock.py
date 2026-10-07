"""
Verify a humanized mousemove toward a viewport edge does not deadlock (daijro/camoufox#225).

Camoufox dispatches synthesized mouse events inside `activateAndRun()`
(additions/juggler/TargetRegistry.js), which serializes every dispatch on a
*process-global* promise chain. Each dispatch awaits a `hit-renderer` ack from
the content process. If an ack never arrives, the callback never returns, the
global chain never advances, and every later input event in the process hangs
behind it forever.

A mousemove at exactly x==width or y==height fires as an exit event rather than
eMouseMove, so no ack is ever produced. Commit 9270618 fixed this for the
*requested endpoint* by treating exact-edge coordinates as out-of-viewport
(`>=` rather than `>`, PageHandler.js:589).

The humanize trajectory added later (commit 15f2912, #677) introduced a second,
independent bounds check for the *intermediate* points it generates, written in
the old strict-`>` form -- so those points bypass the endpoint guard entirely
and can still land exactly on the edge:

    PageHandler.js:566   currentX >  boundingBox.width   <-- intermediate points
    PageHandler.js:589   x        >= boundingBox.width   <-- requested endpoint

This is reachable rather than theoretical, and it stayed reachable when the
generator was replaced. Trajectory points are rounded to whole pixels, and the
path does not stay between its endpoints: measured over 400 random moves,
Cursory's paths stray a median of 33-57px perpendicular to the straight line
(up to 214px), and 69% leave the box spanned by their own endpoints entirely.
So a target anywhere near an edge produces a curve that sweeps across the
boundary column and lands on it exactly. Points *beyond* the edge are skipped
safely by the `continue`; points *on* it are dispatched and hang.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python3 browser/tests/playwright/patches/humanize-edge-deadlock.py

What PASS means:
    * repeated humanized moves toward the right and bottom edges all complete
      within the timeout (no missing ack, no wedged activation chain);
    * the browser still responds to input afterwards, proving the global chain
      is not poisoned.

Before the fix this times out on one of the edge moves. After it, all complete.
"""

import asyncio
import os
import sys

from camoufox.async_api import AsyncCamoufox

VIEWPORT = {"width": 1000, "height": 700}
# Targets inside the viewport but within the trajectory's +/-80px knot boundary
# of an edge, so the generated curve sweeps across the boundary column.
EDGE_TARGETS = [
    (VIEWPORT["width"] - 1, 350),
    (VIEWPORT["width"] - 3, 200),
    (500, VIEWPORT["height"] - 1),
    (500, VIEWPORT["height"] - 3),
    (VIEWPORT["width"] - 2, VIEWPORT["height"] - 2),
]
MOVE_TIMEOUT_S = 20

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")


def _launch_kwargs():
    kwargs = dict(headless=True, os="linux", humanize=True)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


async def main() -> int:
    async with AsyncCamoufox(**_launch_kwargs()) as browser:
        page = await browser.new_page(no_viewport=True)
        await page.set_viewport_size(VIEWPORT)
        await page.set_content(
            f'<body style="margin:0;width:{VIEWPORT["width"]}px;'
            f'height:{VIEWPORT["height"]}px"></body>'
        )

        print(f"\n=== humanized moves toward viewport edges ({VIEWPORT}) ===")
        await page.mouse.move(20, 20)

        for i, (x, y) in enumerate(EDGE_TARGETS, 1):
            label = f"  [{i}/{len(EDGE_TARGETS)}] move -> ({x}, {y})"
            try:
                await asyncio.wait_for(page.mouse.move(x, y), timeout=MOVE_TIMEOUT_S)
            except asyncio.TimeoutError:
                print(f"{label}  FAIL: no ack after {MOVE_TIMEOUT_S}s")
                print(
                    "\n  DEADLOCK: an intermediate trajectory point landed exactly on the\n"
                    "  viewport edge, was dispatched, and never produced a hit-renderer ack.\n"
                    "  The global activation chain is now wedged -- all further input hangs.\n"
                    "  Fix: use >= (not >) in the humanize bounds check, PageHandler.js:566.\n"
                )
                return 1
            print(f"{label}  ok")

        # The chain survived: prove input still works rather than trusting the
        # absence of a timeout above.
        try:
            await asyncio.wait_for(
                page.evaluate(
                    "window.ok=false;"
                    "addEventListener('mousemove',()=>window.ok=true,{once:true})"
                ),
                timeout=MOVE_TIMEOUT_S,
            )
            await asyncio.wait_for(page.mouse.move(400, 300), timeout=MOVE_TIMEOUT_S)
            responsive = await asyncio.wait_for(
                page.evaluate("window.ok"), timeout=MOVE_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            print("\n  FAIL: browser unresponsive after the edge moves")
            return 1

        if not responsive:
            print("\n  FAIL: no mousemove observed after the edge moves")
            return 1

        print("\n  PASS: all edge-directed humanized moves completed; input still live\n")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
