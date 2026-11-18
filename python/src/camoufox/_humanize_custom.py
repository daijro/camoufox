"""
Client-side humanize engines: `custom(fn)` on a channel.

The function runs in this process, never in the browser. It plans a channel's
input and plays it through Playwright's own input methods, so the page sees the
same trusted events as from any Playwright call. The browser runs that channel
raw, as it runs every channel: it has no humanization of its own.

What is wrapped, per page of the browser (or persistent context) it is attached
to, and what the function is called for:

    mouse     Mouse.move / click / dblclick; the move to the click point of
              Page/Frame/Locator click, dblclick, hover, check and uncheck, and
              of the click that focuses a field before fill
    keyboard  Keyboard.type / press; Page/Frame/Locator fill, type, press, and
              Locator.press_sequentially
    scroll    Mouse.wheel; Locator.scroll_into_view_if_needed, and the scroll
              into view before a Page/Frame/Locator click, dblclick, hover,
              check, uncheck, fill, type or press_sequentially when the element
              is not in view

ElementHandle methods, tap, drag_and_drop and drag_to are Playwright's own. An
ElementHandle cannot be scrolled and moved to in the flows below, and a drag's
moves happen inside Playwright's server.

Playwright runs an action inside its own server, so a client wrapper cannot
reach into it. The wrappers act first: they scroll the element into view and
move to the point, so Playwright's own scroll finds nothing to do and its own
move has no distance to cover.

The flows below are generators that yield Playwright calls. One driver awaits
them (async API), another takes their results as they are (sync API), so both
APIs share one implementation.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import math
import secrets
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Dict, Generator, List, Mapping, Optional, Tuple

from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

from ._warnings import LeakWarning
from .driver_defaults import FILL_NEEDS_CLICK, PRESS_MISSES
from .humanize import SeededRng, channel_stream, normalize

# The channels whose function is running in this task. A call a function makes
# on its own channel (page.mouse.move inside a mouse engine) goes straight to
# Playwright instead of back into the function.
_ACTIVE = ContextVar('camoufox_humanize_custom', default=frozenset())

_ENGINES = '_camoufox_custom_engines'
# Marks an engine function that returns a flow rather than a result.
FLOW = '_camoufox_flow'
_ORIGINALS = '_camoufox_custom_originals'
_ROUTED_FRAMES = '_camoufox_custom_routed'
# Where the last move left the cursor on a page, in page px. Playwright does not report it.
POINTER = '_camoufox_custom_pointer'

# Is the element's box inside its frame's viewport?
_IN_VIEW = """e => {
  const r = e.getBoundingClientRect();
  return r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth;
}"""

_BUTTONS = ('left', 'right', 'middle')


class _Sleep:
    __slots__ = ('seconds',)

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds


Flow = Generator[Any, Any, Any]


def _drive_sync(flow: Flow) -> Any:
    value: Any = None
    while True:
        try:
            item = flow.send(value)
        except StopIteration as stop:
            return stop.value
        if isinstance(item, _Sleep):
            time.sleep(item.seconds)
            value = None
        else:
            # The sync API already returned the call's result.
            value = item


async def _drive_async(flow: Flow) -> Any:
    value: Any = None
    error: Optional[BaseException] = None
    while True:
        try:
            item = flow.throw(error) if error is not None else flow.send(value)
        except StopIteration as stop:
            return stop.value
        value, error = None, None
        try:
            if isinstance(item, _Sleep):
                await asyncio.sleep(item.seconds)
            elif inspect.isawaitable(item):
                value = await item
            else:
                value = item
        except BaseException as e:  # noqa: BLE001 -- handed back to the flow
            error = e


class _Engines:
    """The custom engines of one browser: the functions, their streams, and
    how to run a flow in this API."""

    def __init__(self, fns: Mapping[str, Callable[..., Any]], seed: int, is_async: bool) -> None:
        self.fns = dict(fns)
        self.seed = seed
        self.is_async = is_async
        self.rng: Dict[str, SeededRng] = {channel: channel_stream(seed, channel) for channel in fns}

    def fn(self, channel: str) -> Optional[Callable[..., Any]]:
        """The channel's function, or None when it has none or is already running."""
        if channel in _ACTIVE.get():
            return None
        return self.fns.get(channel)

    def run(self, flow: Flow) -> Any:
        return _drive_async(flow) if self.is_async else _drive_sync(flow)


def _originals(page: Any) -> Dict[str, Callable[..., Any]]:
    return getattr(page, _ORIGINALS)


def _call(engines: _Engines, channel: str, page: Any, args: Tuple, original: Callable[..., Any], **extra: Any) -> Flow:
    """Call the channel's function, with its own channel passed through. A
    built-in engine (`FLOW`) returns a flow, run in this API as the call's own."""
    fn = engines.fns[channel]
    token = _ACTIVE.set(_ACTIVE.get() | {channel})
    try:
        result = fn(page, *args, original=original, rng=engines.rng[channel], play=_player(engines, page), **extra)
        if getattr(fn, FLOW, False):
            return (yield from result)
        return (yield result)
    finally:
        _ACTIVE.reset(token)


def _player(engines: _Engines, page: Any) -> Callable[[Any], Any]:
    def play(steps: Any) -> Any:
        return engines.run(_play(page, steps))

    return play


# ---- play(): schedule-paced dispatch ---------------------------------------

def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_steps(steps: Any) -> List[Tuple[str, Tuple, float]]:
    """
    The steps of a play() call as (kind, args, t), or ValueError naming the
    first bad step. Nothing is dispatched unless every step is valid.

        ('move', x, y, t)   ('down', button, t)   ('up', button, t)
        ('wheel', dx, dy, t)   ('key', key, 'down' | 'up', t)   ('text', text, t)

    t is milliseconds from the start of the call, non-decreasing.
    """
    if isinstance(steps, (str, bytes, Mapping)) or not hasattr(steps, '__iter__'):
        raise ValueError(f'play() takes a list of steps, got {steps!r}')
    plan: List[Tuple[str, Tuple, float]] = []
    last = 0.0
    for i, step in enumerate(steps):
        def bad(why: str) -> ValueError:
            return ValueError(f'play() step {i} {step!r}: {why}')

        if not isinstance(step, (tuple, list)) or not step or not isinstance(step[0], str):
            raise bad('a step is a tuple such as ("move", x, y, t)')
        kind, *args = step
        arity = {'move': 3, 'down': 2, 'up': 2, 'wheel': 3, 'key': 3, 'text': 2}.get(kind)
        if arity is None:
            raise bad('the kind must be move, down, up, wheel, key or text')
        if len(args) != arity:
            raise bad(f'{kind} takes {arity} values after the kind')
        *values, t = args
        if not _number(t) or t < 0:
            raise bad('t must be a finite number of milliseconds, at least 0')
        if t < last:
            raise bad(f't goes back in time ({t} after {last})')
        last = t
        if kind in ('move', 'wheel') and not all(_number(v) for v in values):
            raise bad(f'{kind} takes finite numbers')
        if kind in ('down', 'up') and values[0] not in _BUTTONS:
            raise bad(f'the button must be one of {_BUTTONS}')
        if kind == 'key' and (not isinstance(values[0], str) or not values[0] or values[1] not in ('down', 'up')):
            raise bad('key takes a key name and "down" or "up"')
        if kind == 'text' and not isinstance(values[0], str):
            raise bad('text takes a string')
        plan.append((kind, tuple(values), float(t)))
    return plan


def _play(page: Any, steps: Any) -> Flow:
    """Dispatch each step at start + t on a monotonic clock, so a late
    round trip delays only its own step and never accumulates."""
    plan = validate_steps(steps)
    o = _originals(page)
    record = []
    start = time.monotonic()
    for i, (kind, values, t) in enumerate(plan):
        wait = start + t / 1000 - time.monotonic()
        if wait > 0:
            yield _Sleep(wait)
        actual = (time.monotonic() - start) * 1000
        if kind == 'move':
            yield o['move'](values[0], values[1])
        elif kind == 'down':
            yield o['down'](button=values[0])
        elif kind == 'up':
            yield o['up'](button=values[0])
        elif kind == 'wheel':
            yield o['wheel'](values[0], values[1])
        elif kind == 'key':
            yield o['key_down' if values[1] == 'down' else 'key_up'](values[0])
        else:
            yield o['insert_text'](values[0])
        record.append({'i': i, 't_planned': t, 't_actual': actual})
    return record


# ---- flows -----------------------------------------------------------------

def _move(engines: _Engines, page: Any, x: float, y: float) -> Flow:
    move = _originals(page)['move']
    return (yield from _call(engines, 'mouse', page, (x, y), lambda *a, **k: move(*(a or (x, y)), **k), click=None))


def _locator_original(locator: Any, name: str) -> Callable[..., Any]:
    return _LOCATOR_ORIGINALS[type(locator)][name]


def _scroll_into_view(engines: _Engines, locator: Any, timeout: Optional[float], if_needed: bool) -> Flow:
    if if_needed and (yield locator.evaluate(_IN_VIEW, timeout=timeout)):
        return None
    scroll = _locator_original(locator, 'scroll_into_view_if_needed')
    return (
        yield from _call(
            engines, 'scroll', locator.page, (locator,),
            lambda **k: scroll(locator, **{'timeout': timeout, **k}),
        )
    )


def _pointer(engines: _Engines, locator: Any, original: Callable[..., Any], params: Dict[str, Any], name: str) -> Optional[Flow]:
    """click / dblclick / hover / check / uncheck: scroll into view, then the
    mouse engine moves to the point and presses where the cursor is. A point
    something else covers is reached for again, on Playwright's retry schedule."""
    mouse, scroll = engines.fn('mouse'), engines.fn('scroll')
    if not (mouse or scroll) or params.get('trial'):
        return None

    def flow() -> Flow:
        timeout = params.get('timeout')
        if timeout is None:
            timeout = locator.page._impl_obj._timeout_settings.timeout()
        # 0 is no timeout, as in Playwright.
        deadline = time.monotonic() + timeout / 1000 if timeout else math.inf
        if scroll:
            yield from _scroll_into_view(engines, locator, timeout, if_needed=True)
        if not mouse:
            return (yield original(locator, **params))
        click = {k: v for k, v in params.items() if k in _CLICK_PARAMS}
        click.setdefault('click_count', 2 if name == 'dblclick' else 1)
        click.setdefault('button', 'left')
        for attempt in itertools.count():
            if not scroll:
                # The point must be on screen; the browser's scroll engine plans this.
                yield _locator_original(locator, 'scroll_into_view_if_needed')(locator, timeout=timeout)
            box = yield locator.bounding_box(timeout=timeout)
            if not box:
                return (yield original(locator, **params))
            left, top = yield locator.evaluate(BORDERS, timeout=timeout)
            position = params.get('position')
            if position:
                x, y = box['x'] + left + position['x'], box['y'] + top + position['y']
            else:
                x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
            if name in ('check', 'uncheck') and (yield locator.is_checked(timeout=timeout)) == (name == 'check'):
                return None

            def reach(px: float, py: float) -> Flow:
                if not params.get('force'):
                    miss = yield locator.evaluate(PRESS_MISSES, [px - box['x'], py - box['y'], name != 'hover'])
                    if miss:
                        raise _Missed(miss)

            def press(px: float = x, py: float = y, *, delay: Optional[float] = None) -> Any:
                def pressing() -> Flow:
                    yield from reach(px, py)
                    yield from _press(locator.page, px, py, click['button'], click['click_count'], delay,
                                      click.get('modifiers') or ())
                return engines.run(pressing())

            try:
                if name == 'hover':
                    yield from _move(engines, locator.page, x, y)
                    yield from reach(*getattr(locator.page, POINTER))
                else:
                    yield from _call(
                        engines, 'mouse', locator.page, (x, y), press,
                        click={'button': click['button'], 'click_count': click['click_count'],
                               'box': None if position else box},
                    )
                break
            except _Missed as missed:
                if time.monotonic() >= deadline:
                    raise PlaywrightTimeoutError(f'Timeout {timeout:g}ms exceeded: {name} {missed}') from None
                yield _Sleep(_RETRY_MS[min(attempt, len(_RETRY_MS) - 1)] / 1000)
        if name in ('check', 'uncheck') and (yield locator.is_checked(timeout=timeout)) != (name == 'check'):
            raise RuntimeError(f'Clicking the checkbox did not change its state ({name})')
        return None

    return flow()


class _Missed(Exception):
    """A press would not reach its element: something covers the point."""


# Playwright's waits between attempts at a pointer action.
_RETRY_MS = (0, 20, 100, 100, 500)


def _press(page: Any, x: float, y: float, button: str, count: int, delay: Optional[float], modifiers: Any) -> Flow:
    """Press `count` times at (x, y), holding each press `delay` ms and waiting
    as long between presses, as Playwright's click does. The cursor moves there
    first only if it is somewhere else."""
    o = _originals(page)
    if getattr(page, POINTER, None) != (x, y):
        yield o['move'](x, y)
    for key in modifiers:
        yield o['key_down'](key)
    for i in range(1, count + 1):
        if i > 1 and delay:
            yield _Sleep(delay / 1000)
        yield o['down'](button=button, click_count=i)
        if delay:
            yield _Sleep(delay / 1000)
        yield o['up'](button=button, click_count=i)
    for key in reversed(modifiers):
        yield o['key_up'](key)


# Playwright offsets a click's position by the computed border widths. An
# element's clientLeft can differ: a themed text input's includes its frame.
BORDERS = 'e => [getComputedStyle(e).borderLeftWidth, getComputedStyle(e).borderTopWidth].map(v => parseInt(v, 10))'

# Locator.click parameters a press honours; position and delay are the engine's.
_CLICK_PARAMS = ('button', 'click_count', 'modifiers')


def _click_to_focus(engines: _Engines, locator: Any, params: Dict[str, Any]) -> Flow:
    """The click before a fill (driver_defaults), with the mouse engine's move.
    The fill's own hook then finds the field focused."""
    timeout = params.get('timeout')
    if not (yield locator.evaluate(FILL_NEEDS_CLICK, timeout=timeout)):
        return
    yield _locator_original(locator, 'scroll_into_view_if_needed')(locator, timeout=timeout)
    if (yield locator.evaluate(PRESS_MISSES, timeout=timeout)) is None:
        click = {'timeout': timeout, 'force': params.get('force')}
        original = _locator_original(locator, 'click')
        pointer = _pointer(engines, locator, original, click, 'click')
        if pointer:
            yield from pointer
        else:
            yield original(locator, **click)


def _keys(kind: str, text_param: str, focus: str) -> Callable[..., Optional[Flow]]:
    """fill / type / press_sequentially / press on a locator."""

    def make(engines: _Engines, locator: Any, original: Callable[..., Any], params: Dict[str, Any]) -> Optional[Flow]:
        keyboard, scroll = engines.fn('keyboard'), engines.fn('scroll')
        mouse = engines.fn('mouse') if kind == 'fill' else None
        if not (keyboard or mouse or (scroll and kind != 'press')):
            return None
        text = params[text_param]

        def flow() -> Flow:
            timeout = params.get('timeout')
            if scroll and kind != 'press':
                yield from _scroll_into_view(engines, locator, timeout, if_needed=True)
            if mouse or (keyboard and kind == 'fill'):
                yield from _click_to_focus(engines, locator, params)
            if not keyboard or text == '':
                return (yield original(locator, **params))
            if focus == 'select':
                # Typing then replaces what the field held, as fill() does.
                yield locator.select_text(force=params.get('force'), timeout=timeout)
            else:
                yield locator.focus(timeout=timeout)

            def unwrapped(value: Optional[str] = None) -> Any:
                return original(locator, **{**params, text_param: text if value is None else value})

            return (yield from _call(engines, 'keyboard', locator.page, (text,), unwrapped, kind=kind))

        return flow()

    return make


def _scroll_locator(engines: _Engines, locator: Any, original: Callable[..., Any], params: Dict[str, Any]) -> Optional[Flow]:
    if not engines.fn('scroll'):
        return None
    return _scroll_into_view(engines, locator, params.get('timeout'), if_needed=False)


def _pointing(name: str) -> Callable[..., Optional[Flow]]:
    return lambda engines, locator, original, params: _pointer(engines, locator, original, params, name)


_LOCATOR_FLOWS: Dict[str, Callable[..., Optional[Flow]]] = {
    'click': _pointing('click'),
    'dblclick': _pointing('dblclick'),
    'hover': _pointing('hover'),
    'check': _pointing('check'),
    'uncheck': _pointing('uncheck'),
    'fill': _keys('fill', 'value', 'select'),
    'type': _keys('type', 'text', 'focus'),
    'press_sequentially': _keys('type', 'text', 'focus'),
    'press': _keys('press', 'key', 'focus'),
    'scroll_into_view_if_needed': _scroll_locator,
}
_LOCATOR_ORIGINALS: Dict[type, Dict[str, Callable[..., Any]]] = {}


def _bind(original: Callable[..., Any], owner: Any, args: Tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    bound = inspect.signature(original).bind(owner, *args, **kwargs)
    params = dict(bound.arguments)
    params.pop('self', None)
    return params


def _patch_locator_class(cls: type) -> None:
    """Route a Locator class's input methods through the custom engines of the
    locator's page. A page with none (any other browser) gets the original."""
    if cls in _LOCATOR_ORIGINALS:
        return
    originals = _LOCATOR_ORIGINALS[cls] = {name: getattr(cls, name) for name in _LOCATOR_FLOWS}

    for name, original in originals.items():
        def make(name: str, original: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(original)
            def method(self: Any, *args: Any, **kwargs: Any) -> Any:
                engines: Optional[_Engines] = getattr(self.page, _ENGINES, None)
                if engines is None:
                    return original(self, *args, **kwargs)
                params = _bind(original, self, args, kwargs)
                flow = _LOCATOR_FLOWS[name](engines, self, original, params)
                if flow is None:
                    return original(self, **params)
                return engines.run(flow)

            return method

        setattr(cls, name, make(name, original))


# Page and Frame methods that take a selector, routed to the Locator method of
# the same name when one of these channels has a custom engine.
_PAGE_ROUTES = {
    'click': ('mouse', 'scroll'),
    'dblclick': ('mouse', 'scroll'),
    'hover': ('mouse', 'scroll'),
    'check': ('mouse', 'scroll'),
    'uncheck': ('mouse', 'scroll'),
    'fill': ('mouse', 'keyboard', 'scroll'),
    'type': ('keyboard', 'scroll'),
    'press': ('keyboard',),
}


def _attach_page(page: Any, engines: _Engines) -> None:
    if getattr(page, _ENGINES, None) is not None:
        return
    mouse, keyboard = page.mouse, page.keyboard
    raw_move = mouse.move

    def move_raw(x: float, y: float, **kwargs: Any) -> Any:
        setattr(page, POINTER, (x, y))
        return raw_move(x, y, **kwargs)

    o = {
        'move': move_raw, 'down': mouse.down, 'up': mouse.up, 'wheel': mouse.wheel,
        'click': mouse.click, 'dblclick': mouse.dblclick,
        'type': keyboard.type, 'press': keyboard.press,
        'key_down': keyboard.down, 'key_up': keyboard.up, 'insert_text': keyboard.insert_text,
    }
    setattr(page, _ORIGINALS, o)
    setattr(page, _ENGINES, engines)
    _patch_locator_class(type(page.locator('html')))

    def passthrough_unless(channel: str, original: Callable[..., Any], flow: Callable[..., Flow]) -> Callable[..., Any]:
        @wraps(original)
        def method(*args: Any, **kwargs: Any) -> Any:
            if not engines.fn(channel):
                return original(*args, **kwargs)
            return engines.run(flow(*args, **kwargs))

        return method

    if 'mouse' in engines.fns:
        def move(x: float, y: float, *, steps: Optional[int] = None) -> Flow:
            extra = {} if steps is None else {'steps': steps}
            return (yield from _call(
                engines, 'mouse', page, (x, y), lambda *a, **k: o['move'](*(a or (x, y)), **{**extra, **k}),
                click=None,
            ))

        def click_at(name: str) -> Callable[..., Flow]:
            def flow(x: float, y: float, **kwargs: Any) -> Flow:
                count = 2 if name == 'dblclick' else kwargs.get('click_count', 1)
                button = kwargs.get('button', 'left')

                def press(px: float = x, py: float = y, *, delay: Optional[float] = None) -> Any:
                    return engines.run(_press(page, px, py, button, count, delay, ()))

                return (yield from _call(
                    engines, 'mouse', page, (x, y), press, click={'button': button, 'click_count': count, 'box': None},
                ))

            return flow

        mouse.move = passthrough_unless('mouse', o['move'], move)
        mouse.click = passthrough_unless('mouse', o['click'], click_at('click'))
        mouse.dblclick = passthrough_unless('mouse', o['dblclick'], click_at('dblclick'))

    if 'scroll' in engines.fns:
        def wheel(delta_x: float, delta_y: float) -> Flow:
            return (yield from _call(
                engines, 'scroll', page, ((delta_x, delta_y),),
                lambda *a: o['wheel'](*(a or (delta_x, delta_y))),
            ))

        mouse.wheel = passthrough_unless('scroll', o['wheel'], wheel)

    if 'keyboard' in engines.fns:
        def keys(name: str, kind: str) -> Callable[..., Flow]:
            def flow(text: str, *, delay: Optional[float] = None) -> Flow:
                extra = {} if delay is None else {'delay': delay}
                return (yield from _call(
                    engines, 'keyboard', page, (text,),
                    lambda value=None: o[name](text if value is None else value, **extra), kind=kind,
                ))

            return flow

        keyboard.type = passthrough_unless('keyboard', o['type'], keys('type', 'type'))
        keyboard.press = passthrough_unless('keyboard', o['press'], keys('press', 'press'))

    # page.click(selector) and friends: the same flow as the locator's.
    for name, channels in _PAGE_ROUTES.items():
        if any(channel in engines.fns for channel in channels):
            setattr(page, name, _routed(getattr(page, name), page, name))
    _patch_frame_class(type(page.main_frame))


def _routed(original: Callable[..., Any], owner: Any, name: str) -> Callable[..., Any]:
    @wraps(original)
    def method(selector: str, *args: Any, **kwargs: Any) -> Any:
        params = dict(inspect.signature(original).bind(selector, *args, **kwargs).arguments)
        params.pop('selector')
        strict = params.pop('strict', None)
        locator = owner.locator(selector)
        # Without strict, Page and Frame methods act on the first match.
        return getattr(locator if strict else locator.first, name)(**params)

    return method


def _patch_frame_class(cls: type) -> None:
    """Route a Frame class's input methods as a page's are, for frames of a
    page with custom engines on one of the channels."""
    if _ROUTED_FRAMES in cls.__dict__:
        return
    setattr(cls, _ROUTED_FRAMES, True)
    for name, channels in _PAGE_ROUTES.items():
        def make(original: Callable[..., Any], name: str, channels: Tuple[str, ...]) -> Callable[..., Any]:
            @wraps(original)
            def method(self: Any, *args: Any, **kwargs: Any) -> Any:
                engines: Optional[_Engines] = getattr(self.page, _ENGINES, None)
                if engines is None or not any(channel in engines.fns for channel in channels):
                    return original(self, *args, **kwargs)
                return _routed(original.__get__(self), self, name)(*args, **kwargs)

            return method

        setattr(cls, name, make(getattr(cls, name), name, channels))


def _attach_context(context: Any, engines: _Engines) -> None:
    if getattr(context, _ENGINES, None) is not None:
        return
    setattr(context, _ENGINES, engines)
    context.on('page', lambda page: _attach_page(page, engines))
    for page in context.pages:
        _attach_page(page, engines)


def _is_async(target: Any) -> bool:
    from playwright._impl._async_base import AsyncBase

    return isinstance(target, AsyncBase)


def check(humanize: Any, is_async: bool) -> None:
    """Check a `humanize` setting before a launch."""
    engines, _seed = normalize(humanize)
    if not is_async:
        for channel, engine in engines.items():
            fn = engine.get('fn')
            if inspect.iscoroutinefunction(fn):
                raise ValueError(
                    f'humanize["{channel}"]: custom({getattr(fn, "__name__", fn)}) is async, but this is the '
                    'sync API. Pass a plain function, or use AsyncCamoufox.'
                )


def attach(
    target: Any,
    humanize: Any,
    os: str,
    seed: Optional[int] = None,
    i_know_what_im_doing: Optional[bool] = None,
    is_async: Optional[bool] = None,
) -> Any:
    """
    Run the engines of a `humanize` setting on every page of `target`, a
    Browser or BrowserContext, including pages and contexts opened later.
    Other browsers in this process are untouched. `os` ('macos', 'windows' or
    'linux') is the launch identity's, whose people myuri plans for.

    The streams use `humanize["seed"]`, or `seed`, or a random seed.
    """
    if is_async is None:
        is_async = _is_async(target)
    check(humanize, is_async)
    channels, given = normalize(humanize)
    fns: Dict[str, Callable[..., Any]] = {}
    for channel, engine in channels.items():
        if engine['engine'] == 'custom':
            fns[channel] = engine['fn']
        elif engine['engine'] == 'myuri':
            from ._humanize_myuri import engine as myuri_engine

            fns[channel] = myuri_engine(channel, engine['options'], os)
    if not fns:
        return target
    if getattr(target, _ENGINES, None) is not None:
        raise ValueError('humanize engines are already attached to this browser')
    impl = getattr(target, '_impl_obj', None)
    if getattr(getattr(impl, '_connection', None), 'is_remote', False):
        LeakWarning.warn('humanize_custom_remote', i_know_what_im_doing)

    if given is None:
        given = seed if seed is not None else secrets.randbits(64)
    engines = _Engines(fns, given, is_async)

    if not hasattr(target, 'new_context'):
        # A BrowserContext (a persistent context).
        _attach_context(target, engines)
        return target

    setattr(target, _ENGINES, engines)
    for context in target.contexts:
        _attach_context(context, engines)

    def on_context(context: Any) -> Any:
        _attach_context(context, engines)
        return context

    def on_page(page: Any) -> Any:
        _attach_context(page.context, engines)
        _attach_page(page, engines)
        return page

    for name, then in (('new_context', on_context), ('new_page', on_page)):
        original = getattr(target, name)

        def make(original: Callable[..., Any], then: Callable[[Any], Any]) -> Callable[..., Any]:
            if is_async:
                @wraps(original)
                async def method(*args: Any, **kwargs: Any) -> Any:
                    return then(await original(*args, **kwargs))
            else:
                @wraps(original)
                def method(*args: Any, **kwargs: Any) -> Any:
                    return then(original(*args, **kwargs))

            return method

        setattr(target, name, make(original, then))
    return target
