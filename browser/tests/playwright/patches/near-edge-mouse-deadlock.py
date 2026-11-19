"""
Verify a mouse event on the viewport's top edge does not deadlock (daijro/camoufox#751, #752).

Camoufox dispatches synthesized mouse events inside `activateAndRun()`
(additions/juggler/TargetRegistry.js), which serializes every dispatch on a
*process-global* promise chain. Each dispatch awaits a `hit-renderer` ack from
the content process. If an ack never arrives, the callback never returns, the
global chain never advances, and every later input event in the process hangs
behind it forever. Two triggers were already fixed: the far edges (x==width / y==height, #225,
now swept by mouse-boundary-sweep.py) and a zero-displacement move
(noop-mousemove-deadlock.py). This is the third: the
*near* edge, y==0.

MECHANISM
`sendOne()` in PageHandler.js dispatches at `eventY + boundingBox.top`, so a
relative y of 0 dispatches at absolute y == `boundingBox.top` exactly -- the
first row of the content area. That row is only partly covered whenever the
chrome above it is a fractional number of CSS pixels tall, and the widget rounds
the coordinate to a whole device row before hit-testing it. When
`round(top) < top` the rounded row still belongs to chrome, the event fires as
an exit event rather than eMouseMove, no ack is produced, and the chain wedges.

That makes it a deterministic property of the chrome height, which Camoufox
varies with the spoofed OS. Measured on this build by logging `boundingBox` at
the dispatch site, and pairing each offset with the outcome of a single move:

    os          boundingBox.top   rounds to   page.mouse.move(31, 0)
    windows     51.4              51  (above) hangs, 5/5
    macos       53.1              53  (above) hangs, 5/5
    linux       56.5              57  (below) completes, 8/8

So the default randomized fingerprint reaches it on most launches, and a run
that spoofs Linux never does -- which is why this went unnoticed while the
far-edge guards were in place. Relative x == 0 is unaffected for the same
reason: `boundingBox.left` is a whole 0, so it needs no rounding.

WHY NOT WIDEN THE BOUNDS CHECK
The far edges were fixed by treating them as out-of-viewport. 0 cannot be: it is
a legitimate in-viewport coordinate a caller may ask for, and the out-of-viewport
branch silently drops mousedown/mouseup, so widening the check would turn the
hang into a click that reports success and fires nothing (#752). The fix snaps
the dispatched coordinate to the first whole pixel inside the browser element,
which stays within content pixel 0 while landing clear of the boundary.

COVERAGE
`page.mouse.move(x, 0)` reaches the conversion directly, deterministic on an
affected chrome offset. (A since-removed in-browser cursor trajectory reached it
too, by riding the y==0 row from its (0, 0) start; a driver that plans curves
sends each point as its own move, so this covers it.)

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python3 browser/tests/playwright/patches/near-edge-mouse-deadlock.py

What PASS means:
    * a move onto the top edge completes on every spoofed OS, and the page
      actually observes it -- an event swallowed by chrome leaves no mousemove;
    * the browser still responds to input afterwards, proving the global chain
      is not poisoned.

Before the fix the first direct move times out; after it, every move completes.
"""

import asyncio
import sys

from camoufox.async_api import AsyncCamoufox
from helpers import launch_kwargs

# The chrome height, and so whether the top row rounds into chrome, depends on
# the spoofed OS. Cover all three rather than assuming which one this host's
# chrome puts on the wrong side of the boundary.
SPOOFED_OSES = ["windows", "macos", "linux"]
# Relative y == 0 is the deadlock coordinate. x is varied only to show it is the
# whole row that is poisoned, not one particular pixel.
TOP_EDGE_TARGETS = [(31, 0), (0, 0), (500, 0)]
INTERIOR = (250, 250)
TIMEOUT_S = 20

RECORDER = "window.__moves=0;addEventListener('mousemove',()=>window.__moves++)"


def _deadlock_report(what):
    print(
        f"\n  DEADLOCK: {what} produced no hit-renderer ack. The global activation\n"
        "  chain is now wedged -- all further input hangs.\n"
        "  Fix: snap the dispatched coordinate to the first whole pixel inside the\n"
        "  browser element in PageHandler.js sendOne(), so a relative 0 does not\n"
        "  land on the fractional chrome/content boundary.\n"
    )


async def _direct_moves() -> bool:
    """A plain move onto the top edge must complete and be seen by the page."""
    print("\n=== direct moves onto the top edge ===")
    for spoofed_os in SPOOFED_OSES:
        async with AsyncCamoufox(**launch_kwargs(os=spoofed_os)) as browser:
            page = await browser.new_page()
            await page.set_content('<body style="margin:0;height:1200px"></body>')
            await page.evaluate(RECORDER)
            # Start from an interior point so the move under test is a real
            # displacement, not a no-op skipped before dispatch.
            await asyncio.wait_for(page.mouse.move(*INTERIOR), timeout=TIMEOUT_S)

            for x, y in TOP_EDGE_TARGETS:
                label = f"  [{spoofed_os}] move -> ({x}, {y})"
                before = await page.evaluate("window.__moves")
                try:
                    await asyncio.wait_for(page.mouse.move(x, y), timeout=TIMEOUT_S)
                except asyncio.TimeoutError:
                    print(f"{label}  FAIL: no ack after {TIMEOUT_S}s")
                    _deadlock_report(f"a mousemove at ({x}, {y})")
                    return False
                after = await asyncio.wait_for(
                    page.evaluate("window.__moves"), timeout=TIMEOUT_S
                )
                if after == before:
                    print(f"{label}  FAIL: dispatched but the page saw no mousemove")
                    print(
                        "\n  The event was delivered outside the content area. It did not\n"
                        "  hang this time, but it never reached the renderer either.\n"
                    )
                    return False
                print(f"{label}  ok")
                await asyncio.wait_for(page.mouse.move(*INTERIOR), timeout=TIMEOUT_S)

            # The chain survived: prove input still works rather than trusting the
            # absence of a timeout above.
            try:
                await asyncio.wait_for(page.mouse.move(400, 300), timeout=TIMEOUT_S)
                live = await asyncio.wait_for(
                    page.evaluate("window.__moves"), timeout=TIMEOUT_S
                )
            except asyncio.TimeoutError:
                print(f"  [{spoofed_os}] FAIL: unresponsive after the edge moves")
                return False
            if not live:
                print(f"  [{spoofed_os}] FAIL: no mousemove observed at all")
                return False
    return True


async def main() -> int:
    if not await _direct_moves():
        return 1
    print("\n  PASS: top-edge moves completed and were seen; input still live\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
