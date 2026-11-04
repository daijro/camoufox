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

The timing check is the other half, and it is measured against stock Firefox,
not against the recordings. A mouse reports every few milliseconds, but Firefox
coalesces pointer motion and delivers at most one mousemove per refresh tick.
Stock Firefox 158 on Xvfb, driven by XTest motion at irregular 3-15 ms
intervals, gave a page gaps of 16-18 ms in three runs of 155-164 moves, with
requestAnimationFrame ticking every 17.1 ms. A synthesized move dispatches at
once, so the page saw the trajectory's own clock, gaps of 5-13 ms (faster than
any refresh). Stock dispatches each move at the refresh tick itself: 90-91% of
its moves landed within 2.5 ms of a requestAnimationFrame callback, against
19-43% of synthesized ones, which landed anywhere in the frame. So a humanized
move must deliver its points at refresh ticks, as the page's own rAF measures
them, with a median gap of one frame.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python browser/tests/playwright/patches/humanize-mouse-trajectory.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make -C browser stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * humanize=True expands one long mouse.move into many intermediate
      mousemove events, ending exactly on the requested destination;
    * those events are spread over a plausible human duration, one per
      refresh frame as stock Firefox delivers a real mouse's motion;
    * a humanized click still lands on the target element;
    * without humanize, each move emits only its endpoint (pins the other
      direction so accidental always-on humanization is also caught).
"""

import asyncio
import bisect
import statistics
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
    window.frames = [];
    (function tick(t) { frames.push(t); requestAnimationFrame(tick); })(performance.now());
"""
# How close to a requestAnimationFrame callback, on either side, a mousemove
# counts as delivered at the refresh tick, and the share that must be: below
# stock's 90%, far above the 19-43% of moves played on the generator's clock.
TICK_MS = 2.5
AT_TICK = 0.75
# Most gaps of a move are exactly one frame; a pause in the hand is whole frames.
MEDIAN_FRAMES = (0.85, 1.25)

# The default humanize ceiling is 1.5s, and playback may end up to a frame past
# it; anything under 50ms for a ~1200px move means the trajectory is being
# emitted as fast as the event loop allows.
MIN_DURATION_MS = 50
MAX_DURATION_MS = 1550


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
        if humanize:
            # Only the move to dest is measured.
            await page.evaluate("moves = []; frames = []")
        await page.mouse.move(*dest)
        return await page.evaluate("moves"), dest, await page.evaluate("frames")


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


def _tick_distance(t, frames):
    """How far a timestamp lies from the nearest requestAnimationFrame callback."""
    i = bisect.bisect_left(frames, t)
    return min(abs(frames[j] - t) for j in (i - 1, i) if 0 <= j < len(frames))


def _gaps(moves):
    """Inter-event gaps, in ms, of the measured move."""
    times = [m[2] for m in moves]
    return [round(b - a, 1) for a, b in zip(times, times[1:])]


async def main() -> int:
    passed = True

    humanized, dest, frames = await _collect_moves(True)
    frame_ms = statistics.median(b - a for a, b in zip(frames, frames[1:]))
    print("\n=== humanize=True ===")
    print(f"  mousemove events: {len(humanized)}  (endpoint: {humanized[-1][:2] if humanized else None})")
    if len(humanized) >= 10 and humanized[-1][:2] == list(dest):
        print("  PASS: humanized trajectory emitted, ending on destination")
    else:
        passed = False
        print("  FAIL: expected >=10 intermediate points ending exactly on the destination")

    gaps = _gaps(humanized)
    duration = round(sum(gaps), 1)
    print(f"  duration: {duration}ms over {len(gaps)} gaps; page frame {frame_ms:.1f}ms")
    print(f"  gaps: {gaps}")
    if MIN_DURATION_MS <= duration <= MAX_DURATION_MS:
        print("  PASS: movement spans a plausible human duration")
    else:
        passed = False
        print(f"  FAIL: expected {MIN_DURATION_MS}-{MAX_DURATION_MS}ms, got {duration}ms")
    at_tick = sum(1 for m in humanized if _tick_distance(m[2], frames) <= TICK_MS)
    share = at_tick / len(humanized) if humanized else 0
    median = statistics.median(gaps) if gaps else 0
    if share >= AT_TICK and MEDIAN_FRAMES[0] * frame_ms <= median <= MEDIAN_FRAMES[1] * frame_ms:
        print(f"  PASS: delivered at refresh ticks ({share:.0%}), median gap {median}ms")
    else:
        passed = False
        print(f"  FAIL: {share:.0%} of mousemoves within {TICK_MS}ms of a refresh tick "
              f"(need {AT_TICK:.0%}), median gap {median}ms against a {frame_ms:.1f}ms frame")

    plain, plain_dest, _ = await _collect_moves(False)
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
