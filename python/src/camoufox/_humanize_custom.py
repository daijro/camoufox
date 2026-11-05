"""
Client-side humanize engines: `custom(fn)` on a channel.

The function runs in this process, never in the browser. It plans a channel's
input and plays it through Playwright's own input methods, so the page sees the
same trusted events as from any Playwright call. The browser runs that channel
raw (camoufox.humanize.humanize_config), so input is never humanized twice.

What is wrapped, per page of the browser (or persistent context) it is attached
to, and what the function is called for:

    mouse     Mouse.move / click / dblclick; the move to the click point of
              Page/Locator click, dblclick and hover
    keyboard  Keyboard.type / press; Page/Locator fill, type, press, and
              Locator.press_sequentially
    scroll    Mouse.wheel; Locator.scroll_into_view_if_needed, and the scroll
              into view before a Page/Locator click, dblclick, hover, fill,
              type or press_sequentially when the element is not in view

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
import math
import secrets
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Dict, Generator, List, Mapping, Optional, Tuple

from ._warnings import LeakWarning
from .humanize import SeededRng, channel_stream, custom_engines, normalize

# The channels whose function is running in this task. A call a function makes
# on its own channel (page.mouse.move inside a mouse engine) goes straight to
# Playwright instead of back into the function.
_ACTIVE = ContextVar('camoufox_humanize_custom', default=frozenset())

_ENGINES = '_camoufox_custom_engines'
_ORIGINALS = '_camoufox_custom_originals'

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
    """Call the channel's function, with its own channel passed through."""
    fn = engines.fns[channel]
    token = _ACTIVE.set(_ACTIVE.get() | {channel})
    try:
        return (
            yield fn(
                page,
                *args,
                original=original,
                rng=engines.rng[channel],
                play=_player(engines, page),
                **extra,
            )
        )
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
    return (yield from _call(engines, 'mouse', page, (x, y), lambda *a, **k: move(*(a or (x, y)), **k)))


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


def _pointer(engines: _Engines, locator: Any, original: Callable[..., Any], params: Dict[str, Any]) -> Optional[Flow]:
    """click / dblclick / hover: scroll into view, move to the point, then
    Playwright's own action, whose move is then zero-length."""
    mouse, scroll = engines.fn('mouse'), engines.fn('scroll')
    if not (mouse or scroll) or params.get('trial'):
        return None

    def flow() -> Flow:
        timeout = params.get('timeout')
        if scroll:
            yield from _scroll_into_view(engines, locator, timeout, if_needed=True)
        if mouse:
            if not scroll:
                # The point must be on screen; the browser's scroll engine plans this.
                yield _locator_original(locator, 'scroll_into_view_if_needed')(locator, timeout=timeout)
            box = yield locator.bounding_box(timeout=timeout)
            if box:
                position = params.get('position')
                if position:
                    # position is relative to the padding box
                    left, top = yield locator.evaluate('e => [e.clientLeft, e.clientTop]', timeout=timeout)
                    x, y = box['x'] + left + position['x'], box['y'] + top + position['y']
                else:
                    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
                yield from _move(engines, locator.page, x, y)
        return (yield original(locator, **params))

    return flow()


def _keys(kind: str, text_param: str, focus: str) -> Callable[..., Optional[Flow]]:
    """fill / type / press_sequentially / press on a locator."""

    def make(engines: _Engines, locator: Any, original: Callable[..., Any], params: Dict[str, Any]) -> Optional[Flow]:
        keyboard, scroll = engines.fn('keyboard'), engines.fn('scroll')
        if not (keyboard or (scroll and kind != 'press')):
            return None
        text = params[text_param]

        def flow() -> Flow:
            timeout = params.get('timeout')
            if scroll and kind != 'press':
                yield from _scroll_into_view(engines, locator, timeout, if_needed=True)
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


_LOCATOR_FLOWS: Dict[str, Callable[..., Optional[Flow]]] = {
    'click': _pointer,
    'dblclick': _pointer,
    'hover': _pointer,
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


# Page methods that take a selector, routed to the Locator method of the same
# name when one of these channels has a custom engine.
_PAGE_ROUTES = {
    'click': ('mouse', 'scroll'),
    'dblclick': ('mouse', 'scroll'),
    'hover': ('mouse', 'scroll'),
    'fill': ('keyboard', 'scroll'),
    'type': ('keyboard', 'scroll'),
    'press': ('keyboard',),
}


def _attach_page(page: Any, engines: _Engines) -> None:
    if getattr(page, _ENGINES, None) is not None:
        return
    mouse, keyboard = page.mouse, page.keyboard
    o = {
        'move': mouse.move, 'down': mouse.down, 'up': mouse.up, 'wheel': mouse.wheel,
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
                engines, 'mouse', page, (x, y), lambda *a, **k: o['move'](*(a or (x, y)), **{**extra, **k})
            ))

        def click_at(name: str) -> Callable[..., Flow]:
            def flow(x: float, y: float, **kwargs: Any) -> Flow:
                yield from _move(engines, page, x, y)
                return (yield o[name](x, y, **kwargs))

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
        if not any(channel in engines.fns for channel in channels):
            continue
        original = getattr(page, name)

        def make(name: str, original: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(original)
            def method(selector: str, *args: Any, **kwargs: Any) -> Any:
                params = dict(inspect.signature(original).bind(selector, *args, **kwargs).arguments)
                params.pop('selector')
                strict = params.pop('strict', None)
                locator = page.locator(selector)
                # Without strict, Page methods act on the first match.
                return getattr(locator if strict else locator.first, name)(**params)

            return method

        setattr(page, name, make(name, original))


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


def check(humanize: Any, is_async: bool) -> Dict[str, Callable[..., Any]]:
    """The custom engines of a `humanize` setting, checked before a launch."""
    fns = custom_engines(humanize)
    if not is_async:
        for channel, fn in fns.items():
            if inspect.iscoroutinefunction(fn):
                raise ValueError(
                    f'humanize["{channel}"]: custom({getattr(fn, "__name__", fn)}) is async, but this is the '
                    'sync API. Pass a plain function, or use AsyncCamoufox.'
                )
    return fns


def attach(
    target: Any,
    humanize: Any,
    seed: Optional[int] = None,
    i_know_what_im_doing: Optional[bool] = None,
    is_async: Optional[bool] = None,
) -> Any:
    """
    Run the custom engines of a `humanize` setting on every page of `target`, a
    Browser or BrowserContext, including pages and contexts opened later.
    Other browsers in this process are untouched.

    The streams use `humanize["seed"]`, or `seed`, or a random seed.
    """
    if is_async is None:
        is_async = _is_async(target)
    fns = check(humanize, is_async)
    if not fns:
        return target
    if getattr(target, _ENGINES, None) is not None:
        raise ValueError('custom humanize engines are already attached to this browser')
    impl = getattr(target, '_impl_obj', None)
    if getattr(getattr(impl, '_connection', None), 'is_remote', False):
        LeakWarning.warn('humanize_custom_remote', i_know_what_im_doing)

    _, given = normalize(humanize)
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
