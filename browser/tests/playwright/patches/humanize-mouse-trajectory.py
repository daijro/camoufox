"""
Verify humanize=True produces a human cursor trajectory (daijro/camoufox#677).

Camoufox's cursor humanization has a single call site: the `mousemove` branch of
`sendEvents()` in additions/juggler/protocol/PageHandler.js, which calls
`humanizedSteps()` (additions/juggler/input/CursorTrajectory.js) and dispatches
the intermediate points. The Firefox 146 Juggler migration (commit 03c1230)
rewrote that helper and silently dropped the branch, so from FF146 through v152
`humanize=True` emitted only the endpoint mousemove -- no trajectory at all.

This is runtime-only: the generator, its vendored Cursory backend and the config
plumbing all stay intact and every patch applies cleanly, so nothing fails
loudly. Only driving a real browser and counting the emitted mousemove events
catches it.

The timing check is the other half. Camoufox used to emit trajectory points on a
flat 10ms metronome, which is a giveaway on its own: no hand moves a mouse at a
perfectly constant rate. Cursory carries each recording's own timing, so the
gaps between events must come out uneven -- and a regression that reverted to a
fixed cadence would otherwise pass every other assertion here.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python browser/tests/playwright/patches/humanize-mouse-trajectory.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make -C browser stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * humanize=True expands one long mouse.move into many intermediate
      mousemove events, ending exactly on the requested destination;
    * those events are spread over a plausible human duration, with uneven
      gaps between them rather than a fixed cadence;
    * a humanized click still lands on the target element;
    * without humanize, each move emits only its endpoint (pins the other
      direction so accidental always-on humanization is also caught).
"""

import asyncio
import sys

from camoufox.async_api import AsyncCamoufox
from helpers import launch_kwargs

# The far corner of the move, clamped to the viewport the identity happened to
# draw. It used to be a flat (1100, 650), which silently tested nothing whenever
# the drawn window was smaller than that: the move landed outside the content
# area, no mousemove was delivered, and the run failed reporting only the start
# point. Drawn windows vary far more than they used to (fpgen), and one was
# 924x1364 -- narrower than the old x.
DEST_MAX = (1100, 650)
BODY = '<body style="margin:0;width:1400px;height:800px"></body>'
RECORDER = """
    window.moves = [];
    addEventListener("mousemove", e => moves.push([e.clientX, e.clientY, performance.now()]));
"""

# The default humanize ceiling is 1.5s; anything under 50ms for a ~1200px move
# means the trajectory is being emitted as fast as the event loop allows.
MIN_DURATION_MS = 50
MAX_DURATION_MS = 3000


async def _dest_within(page):
    """DEST_MAX, or the far corner of this viewport if it is smaller."""
    viewport = await page.evaluate("({w: innerWidth, h: innerHeight})")
    return (
        min(DEST_MAX[0], viewport["w"] - 10),
        min(DEST_MAX[1], viewport["h"] - 10),
    )


async def _collect_moves(humanize):
    async with AsyncCamoufox(**launch_kwargs(os="linux", humanize=humanize)) as browser:
        page = await browser.new_page()
        await page.set_content(BODY)
        await page.evaluate(RECORDER)
        dest = await _dest_within(page)
        await page.mouse.move(20, 20)
        await page.mouse.move(*dest)
        return await page.evaluate("moves"), dest


async def _humanized_click_hits_target():
    async with AsyncCamoufox(**launch_kwargs(os="linux", humanize=True)) as browser:
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


def _gaps(moves):
    """Inter-event gaps, in ms, of the trajectory that followed the first move."""
    times = [m[2] for m in moves[1:]]
    return [round(b - a, 1) for a, b in zip(times, times[1:])]


async def main() -> int:
    passed = True

    humanized, dest = await _collect_moves(True)
    print("\n=== humanize=True ===")
    print(f"  mousemove events: {len(humanized)}  (endpoint: {humanized[-1][:2] if humanized else None})")
    if len(humanized) >= 10 and humanized[-1][:2] == list(dest):
        print("  PASS: humanized trajectory emitted, ending on destination")
    else:
        passed = False
        print("  FAIL: expected >=10 intermediate points ending exactly on the destination")

    gaps = _gaps(humanized)
    duration = round(sum(gaps), 1)
    distinct = len(set(gaps))
    print(f"  duration: {duration}ms over {len(gaps)} gaps; {distinct} distinct gap values")
    print(f"  gaps (first 12): {gaps[:12]}")
    if MIN_DURATION_MS <= duration <= MAX_DURATION_MS:
        print("  PASS: movement spans a plausible human duration")
    else:
        passed = False
        print(f"  FAIL: expected {MIN_DURATION_MS}-{MAX_DURATION_MS}ms, got {duration}ms")
    # A metronome would produce one or two distinct values (the fixed step, plus
    # scheduler noise clustering around it). Real recorded timing does not. The
    # page clock is clamped to 1 ms and the recorded steps mostly sit between 12
    # and 20 ms, so the number of distinct values cannot scale with the number
    # of gaps: requiring len(gaps) // 4 failed uneven runs like
    # [19, 18, 18, 17, 88, 18, 21, 15, ...] whenever event delivery was steady.
    # A fixed 10 ms cadence gives about three values within a few ms of each other.
    spread = (max(gaps) - min(gaps)) if gaps else 0
    if distinct >= 6 and spread >= 20:
        print("  PASS: gaps are uneven, not a fixed cadence")
    else:
        passed = False
        print(f"  FAIL: only {distinct} distinct gaps (spread {spread}ms) across {len(gaps)} -- looks like a fixed cadence")

    plain, plain_dest = await _collect_moves(False)
    print("\n=== humanize off ===")
    print(f"  mousemove events: {[m[:2] for m in plain]}")
    if [m[:2] for m in plain] == [[20, 20], list(plain_dest)]:
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
