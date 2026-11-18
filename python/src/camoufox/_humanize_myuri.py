"""
myuri() engines: myuri plans each input for the launch identity's OS, and the
custom-engine wrappers play the plan through Playwright (_humanize_custom).
myuri only plans; nothing here runs in the page except its scroll measurement.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple

from ._humanize_custom import FLOW, POINTER, Flow, _play, _Sleep

# An element still out of view after this many wheel plans (one that moves as
# it scrolls) is brought into view by Playwright's own scroll.
_SCROLL_PASSES = 3

# When the last press was released, until the pointer next moves.
_RELEASED = '_camoufox_myuri_released'

_VIEWPORT = '() => [innerWidth, innerHeight]'
_CLIENT_ORIGIN = 'e => { const r = e.getBoundingClientRect(); return [r.x, r.y]; }'


def engine(channel: str, options: Dict[str, Any], os: str) -> Callable[..., Flow]:
    """The function that runs myuri on `channel` for an identity on `os`."""
    from myuri import plan

    def mouse(page: Any, x: float, y: float, *, original: Any, rng: Any, play: Any, click: Any) -> Flow:
        box = click and click['box']
        if box:
            start = plan.Vector(*(yield from _cursor(page, rng)))
            point = plan.plan_point(plan.BoundingBox(**box), rng, start=start)
            x, y = point.x, point.y
        yield from _move_to(plan, os, page, (x, y), rng)
        if not click:
            return None
        released = getattr(page, _RELEASED, None)
        presses = plan.plan_click(rng, os=os, click_count=click['click_count'],
                                  since_release_ms=None if released is None else (time.monotonic() - released) * 1000)
        yield _Sleep(presses['dwell_ms'] / 1000)
        down, up = presses['presses'][0][0], presses['presses'][-1][1]
        # The press holds each press for `delay` and waits it again between
        # presses, so spread the plan's span evenly over those 2n - 1 intervals.
        result = yield original(x, y, delay=(up - down) / (2 * len(presses['presses']) - 1))
        setattr(page, _RELEASED, time.monotonic())
        return result

    def keyboard(page: Any, text: str, *, original: Any, rng: Any, play: Any, kind: str) -> Flow:
        if kind == 'press':
            steps = plan.plan_press(text, rng, os=os)
        else:
            steps = plan.plan_type(text, rng, os=os, wpm=options.get('wpm'))
        return (yield from _play(page, [
            ('text', key, t) if action == 'insert' else ('key', key, action, t) for t, action, key in steps
        ]))

    def scroll(page: Any, target: Any, *, original: Any, rng: Any, play: Any) -> Flow:
        if isinstance(target, tuple):
            return (yield from _wheel(plan, os, page, target, rng))
        for _ in range(_SCROLL_PASSES):
            here = yield from _cursor(page, rng)
            step = yield target.evaluate(plan.SCROLL_PLAN_JS, {
                'finishPosition': plan.SCROLL_FINISH_POSITION, 'pad': plan.SCROLL_PAD, 'edge': plan.SCROLL_EDGE,
                'fromX': here[0], 'fromY': here[1],
            })
            if not step or step['inView']:
                return None
            # The plan is in the element's frame; the mouse is in the page.
            box = yield target.bounding_box()
            origin = yield target.evaluate(_CLIENT_ORIGIN)
            hover = (step['hoverX'] + box['x'] - origin[0], step['hoverY'] + box['y'] - origin[1])
            yield from _move_to(plan, os, page, hover, rng)
            yield from _wheel(plan, os, page, (0, step['deltaY']), rng)
        return (yield original())

    fn = {'mouse': mouse, 'keyboard': keyboard, 'scroll': scroll}[channel]
    setattr(fn, FLOW, True)
    return fn


def _cursor(page: Any, rng: Any) -> Flow:
    """Where the cursor is. Before the first move it is somewhere in the window,
    as a person's is when they start."""
    here: Optional[Tuple[float, float]] = getattr(page, POINTER, None)
    if here is None:
        width, height = yield page.evaluate(_VIEWPORT)
        here = (rng() * width, rng() * height)
        setattr(page, POINTER, here)
    return here


def _move_to(plan: Any, os: str, page: Any, point: Tuple[float, float], rng: Any) -> Flow:
    start = yield from _cursor(page, rng)
    if start == point:
        return None
    setattr(page, _RELEASED, None)
    path = plan.plan_move(plan.Vector(*start), plan.Vector(*point), rng, os=os)
    yield from _play(page, [('move', x, y, t) for x, y, t in path])
    return None


def _wheel(plan: Any, os: str, page: Any, delta: Tuple[float, float], rng: Any) -> Flow:
    # Camoufox identities point with a mouse, whose wheel turns in notches.
    steps = plan.plan_wheel(delta[0], delta[1], rng, os=os, device='mouse')
    return (yield from _play(page, [
        ('wheel', step[1], step[2], step[3]) if step[0] == 'wheel' else ('key', step[1], step[2], step[3])
        for step in steps
    ]))
