"""
Verify humanized input in the browser: myuri's smart actions, run by the
launcher (python/src/camoufox/_humanize_playwright.py), reach the page as
trusted events, and a part the caller replaces runs in myuri's place.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python browser/tests/playwright/patches/humanize.py
Against an unpackaged objdir build, run `make stage-fonts` first.

What PASS means:
    * myuri on every channel, seeded: every event is trusted; each click lands
      inside its element, where the cursor's path ended; a fill types the text;
      an element out of view is wheeled into view first;
    * the parts the caller wraps are called with the element's box, the point
      and the text, and their default() runs myuri's part;
    * a replaced move part draws the path the page sees, and myuri still
      presses where that path ended;
    * the same seed gives the same input; another seed does not;
    * myuri's moves reach the page at refresh ticks, in whole frames, as a
      real mouse's do in stock Firefox.
"""

import asyncio
import bisect
import os
import statistics
import sys

from camoufox.async_api import AsyncCamoufox
from camoufox.humanize import myuri

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

BODY = """<body style="margin:0;height:5000px">
  <input id="name" style="position:absolute;left:40px;top:120px;width:200px">
  <button id="near" style="position:absolute;left:500px;top:300px;width:50px;height:20px">near</button>
  <button id="far" style="position:absolute;left:100px;top:2600px;width:80px;height:30px">far</button>
</body>"""
RECORDER = """() => {
  window.rec = [];
  const round = v => Math.round(v * 100) / 100;
  for (const type of ['mousemove', 'mousedown', 'mouseup', 'click', 'keydown', 'keyup', 'wheel'])
    addEventListener(type, e => rec.push([type, e.isTrusted, round(e.clientX ?? 0), round(e.clientY ?? 0),
                                          e.key ?? '', round(e.deltaY ?? 0), e.target.id]), true);
}"""

# Wheel scrolling lands asynchronously; wait until the page stops moving so
# the next measurement does not depend on timing.
SETTLE = """() => new Promise(resolve => {
  let last = scrollY, same = 0;
  const tick = () => {
    if (scrollY === last) { if (++same >= 10) return resolve(scrollY); }
    else { same = 0; last = scrollY; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})"""

STEPS = 10

# Stock Firefox delivers a real mouse's motion at refresh ticks: on Xvfb 90-91%
# of its mousemoves landed within 2.5 ms of a requestAnimationFrame callback,
# against 19-43% for moves played on a generator's own clock (#978). Gaps are
# whole frames: one while the hand moves, more where it paused; a gap under a
# frame is only the generator's clock, and delivery that skips frames has few
# one-frame gaps.
FRAMES = """() => {
  window.moves = []; window.frames = [];
  addEventListener('mousemove', () => moves.push(performance.now()));
  (function tick(t) { frames.push(t); requestAnimationFrame(tick); })(performance.now());
}"""
TICK_MS = 2.5
AT_TICK = 0.75
SHORT_FRAME = 0.85
MAX_SHORT = 0.1
ONE_FRAME = (0.85, 1.25)
MIN_ONE_FRAME = 0.2


def logged_parts(log):
    """myuri's own parts, wrapped to record what they were called with."""

    async def point(page, box, attempt, *, default, rng, play):
        x, y = await default()
        log.append(["point", [box.x, box.y, box.width, box.height], [x, y]])
        return x, y

    async def type_(page, text, *, default, rng, play):
        log.append(["type", text])
        return await default()

    async def into_view(page, locator, *, default, rng, play):
        log.append(["into_view"])
        return await default()

    return {
        "mouse": myuri(point=point),
        "keyboard": myuri(type=type_),
        "scroll": myuri(into_view=into_view),
    }


def straight_move(paths):
    """A move part of the caller's own: a straight line in STEPS moves."""
    at = [0.0, 0.0]

    async def move(page, x, y, *, default, rng, play):
        sx, sy = at
        steps = [["move", sx + (x - sx) * i / STEPS, sy + (y - sy) * i / STEPS, i * 12] for i in range(1, STEPS + 1)]
        paths.append(steps)
        at[:] = [x, y]
        return await play(steps)

    return {"mouse": myuri(move=move)}


def identity():
    """One machine for every session. A screen that holds the 1000x700 page:
    one that cannot clamps the page. Sessions that drew their own identities
    laid the page out a device pixel apart (their fonts and pixel ratios), so
    the same seed pressed other points."""
    from camoufox.fingerprints import Screen, generate_fingerprint

    return generate_fingerprint(os="linux", screen=Screen(min_width=1100, min_height=800))


async def session(humanize, fingerprint):
    """The page's events before the far click (laid out the same every run),
    the events of the far click, and the page's state."""
    kwargs = dict(headless=True, os="linux", humanize=humanize, fingerprint=fingerprint, i_know_what_im_doing=True)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    async with AsyncCamoufox(**kwargs) as browser:
        page = await browser.new_page(viewport={"width": 1000, "height": 700})
        await page.set_content(BODY)
        await page.evaluate(RECORDER)
        await page.mouse.move(300, 200)
        await page.mouse.wheel(0, 360)
        await page.evaluate(SETTLE)
        await page.mouse.wheel(0, -360)
        await page.evaluate(SETTLE)
        await page.locator("#near").click()
        await page.locator("#name").fill("Hi there")
        await page.keyboard.press("Tab")
        before = await page.evaluate("rec.splice(0)")
        await page.locator("#far").click()
        state = await page.evaluate(
            "() => [document.querySelector('#name').value,"
            " (r => r.top >= 0 && r.bottom <= innerHeight)(document.querySelector('#far').getBoundingClientRect())]"
        )
        far = await page.evaluate("rec")
    return before, far, state


async def refresh_ticks(fingerprint, failures):
    """One long move of myuri's reaches the page at refresh ticks, in whole frames."""
    kwargs = dict(headless=True, os="linux", humanize=True, fingerprint=fingerprint, i_know_what_im_doing=True)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    async with AsyncCamoufox(**kwargs) as browser:
        page = await browser.new_page(viewport={"width": 1000, "height": 700})
        await page.set_content(BODY)
        await page.mouse.move(20, 20)
        await page.evaluate(FRAMES)
        await page.mouse.move(950, 650)
        moves, frames = await page.evaluate("[moves, frames]")
    frame = statistics.median(b - a for a, b in zip(frames, frames[1:]))
    gaps = [b - a for a, b in zip(moves, moves[1:])]
    if len(gaps) < 10:
        failures.append(f"a long move reached the page as {len(moves)} mousemoves")
        return

    def from_tick(t):
        i = bisect.bisect_left(frames, t)
        return min(abs(frames[j] - t) for j in (i - 1, i) if 0 <= j < len(frames))

    at_tick = sum(from_tick(t) <= TICK_MS for t in moves) / len(moves)
    short = sum(g < SHORT_FRAME * frame for g in gaps) / len(gaps)
    one = sum(ONE_FRAME[0] * frame <= g <= ONE_FRAME[1] * frame for g in gaps) / len(gaps)
    print(f"refresh ticks: {len(moves)} mousemoves, {at_tick:.0%} at a tick; of the gaps, "
          f"{one:.0%} one {frame:.1f} ms frame and {short:.0%} under one")
    if at_tick < AT_TICK or short > MAX_SHORT or one < MIN_ONE_FRAME:
        failures.append(f"myuri's moves are not delivered at refresh ticks in whole frames: {at_tick:.0%} at a "
                        f"tick (need {AT_TICK:.0%}), {one:.0%} one frame (need {MIN_ONE_FRAME:.0%}), "
                        f"{short:.0%} under one (at most {MAX_SHORT:.0%})")


def check_page(label, before, far, state, failures):
    events = before + far
    kinds = [e[0] for e in events]
    clicks = [e for e in events if e[0] == "click"]
    print(f"{label}: {kinds.count('mousemove')} mousemoves, {kinds.count('keydown')} keydowns, "
          f"{kinds.count('wheel')} wheels, clicks on {[c[6] for c in clicks]}; value/far in view: {state}")
    if not all(e[1] for e in events):
        failures.append(f"{label}: an event was not trusted")
    if state != ["Hi there", True]:
        failures.append(f"{label}: expected the text typed and #far in view, got {state}")
    # The click, the click that focuses the input before the fill, the far click.
    if [c[6] for c in clicks] != ["near", "name", "far"]:
        failures.append(f"{label}: expected clicks on near, name and far, got {clicks}")
    for click in clicks:
        moves = [e for e in events[: events.index(click)] if e[0] == "mousemove"]
        if not moves or moves[-1][2:4] != click[2:4]:
            failures.append(f"{label}: the click at {click[2:4]} did not land where the cursor's path ended")
    if not any(e[0] == "wheel" for e in far):
        failures.append(f"{label}: #far was not wheeled into view")
    return clicks


async def main() -> int:
    failures = []
    fingerprint = identity()

    log = []
    before, far, state = await session({**logged_parts(log), "seed": 1234}, fingerprint)
    clicks = check_page("myuri, seed 1234", before, far, state, failures)
    print(f"  parts called: {[entry[0] for entry in log]}")
    if [entry[1] for entry in log if entry[0] == "type"] != ["Hi there"]:
        failures.append(f"the type part was not called with the fill's text: {log}")
    if ["into_view"] not in log:
        failures.append("the into_view part was not called")
    points = [entry for entry in log if entry[0] == "point"]
    if len(points) != len(clicks):
        failures.append(f"expected a point per click, got {points}")
    for (_, (x, y, w, h), at), click in zip(points, clicks):
        if not (x <= at[0] <= x + w and y <= at[1] <= y + h):
            failures.append(f"myuri's point {at} is outside the box {[x, y, w, h]} it was given")
        if [round(v) for v in at] != [round(v) for v in click[2:4]]:
            failures.append(f"the page's click at {click[2:4]} is not the point {at} myuri chose")

    paths = []
    before_m, far_m, state_m = await session({**straight_move(paths), "seed": 1234}, fingerprint)
    ends = [[round(p[-1][1]), round(p[-1][2])] for p in paths]
    for click in check_page("move replaced", before_m, far_m, state_m, failures):
        if [round(v) for v in click[2:4]] not in ends:
            failures.append(f"the click at {click[2:4]} is not where a replaced move ended ({ends})")

    # The same seed replays; another seed does not. Mousemoves are left out:
    # they are coalesced per frame as a real mouse's are, so which ones arrive
    # is a matter of frame timing (each click above still lands where its path
    # ended). A wheel is compared by its delta: its point moves with the page.
    # The far click is left out: wheeling it into view measures the page while
    # the scroll lands, so how many turns it takes depends on frame timing.
    def replayed(events):
        return [[e[0], e[5]] if e[0] == "wheel" else e[2:] for e in events if e[0] != "mousemove"]

    def plan(entries):  # the parts' calls up to the fill's text
        return entries[: entries.index(["type", "Hi there"]) + 1]

    log_b, log_c = [], []
    before_b, _, _ = await session({**logged_parts(log_b), "seed": 1234}, fingerprint)
    before_c, _, _ = await session({**logged_parts(log_c), "seed": 1235}, fingerprint)
    same = replayed(before_b) == replayed(before) and plan(log_b) == plan(log)
    differs = replayed(before_c) != replayed(before)
    print(f"seed 1234 again: same points and page events but moves: {same}; seed 1235 differs: {differs}")
    if not same:
        failures.append("the same seed gave different input")
    if not differs:
        failures.append("another seed gave the same input")

    await refresh_ticks(fingerprint, failures)

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: myuri drives every channel in the browser, its parts can be replaced, and it replays by seed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
