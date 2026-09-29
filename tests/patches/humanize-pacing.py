"""
Verify a humanized move takes the time its path planned, on a busy page.

`sendTrajectoryAcked()` (additions/juggler/input/MouseDispatch.js) dispatches
the intermediate points of a humanized move. Each point carries the pause to
take before it, and each dispatch waits for the renderer's ack. Waiting the
full pause after the ack added every ack's latency to the move, so the move
took its plan plus one round trip per point. A page whose main thread is busy
acks late, and a 0.5 s move of ~25 points ran 0.56-0.9 s.

With the pauses kept as a schedule from the start of the move, a late ack
delays only its own point, and the move still ends on its planned time.

The page here keeps its main thread busy 19 ms of every 20, the way a heavy
page does. humanize=0.5 caps every move at 0.5 s; the long moves below always
reach the cap, so each should take ~0.5 s. Eleven moves are timed from the
page's side and their median is checked, so one move delayed by something
else (a GC, the host) does not decide the result.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/humanize-pacing.py

What PASS means:
    * the median humanized move on a busy page lasts at most 8% longer than
      the humanize cap it was scaled to.
"""

import asyncio
import os
import statistics
import sys

from camoufox.async_api import AsyncCamoufox

CAP_S = 0.5
MAX_MEDIAN_MS = CAP_S * 1000 * 1.08
MOVES = 11

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

BUSY_PAGE = """
    setInterval(() => { const t = performance.now(); while (performance.now() - t < 19); }, 20);
    window.moves = [];
    addEventListener("mousemove", () => moves.push(performance.now()));
"""


async def main() -> int:
    kwargs = dict(headless=True, os="linux", humanize=CAP_S)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    async with AsyncCamoufox(**kwargs) as browser:
        page = await browser.new_page()
        await page.set_content('<body style="margin:0;width:1400px;height:800px"></body>')
        await page.evaluate(BUSY_PAGE)
        viewport = await page.evaluate("({w: innerWidth, h: innerHeight})")
        corners = [(20, 20), (viewport["w"] - 20, viewport["h"] - 20)]
        await page.mouse.move(*corners[0])

        durations = []
        for i in range(MOVES):
            start = await page.evaluate("moves.length")
            await page.mouse.move(*corners[(i + 1) % 2])
            times = await page.evaluate(f"moves.slice({start})")
            if len(times) >= 3:
                durations.append(round(times[-1] - times[0]))

    print(f"move durations (ms): {sorted(durations)}")
    if len(durations) < MOVES - 2:
        print(f"FAIL: only {len(durations)} of {MOVES} moves were humanized")
        return 1
    median = statistics.median(durations)
    if median <= MAX_MEDIAN_MS:
        print(f"PASS: median {median:.0f}ms within {MAX_MEDIAN_MS:.0f}ms of a {CAP_S * 1000:.0f}ms plan")
        return 0
    print(f"FAIL: median {median:.0f}ms; the move took its plan plus the page's ack latency")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
