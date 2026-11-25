"""
myuri's smart actions on Playwright pages.

Each page of the browser (or persistent context) a humanize setting is attached
to gets one `myuri.Actions`. It owns the timing and motion of the page's input
and the decisions around a click: scroll the element into view, choose the
point, check that a press there lands, and try again when it does not. The
host below sends each event through Playwright's own input methods, so the
page sees the same trusted events as from any Playwright call, and the browser
runs every channel raw: it has no humanization of its own.

A raw() channel's parts are Playwright's: its moves are one event, its scroll
into view is Playwright's. A part passed to myuri() is called with the page in
place of the host. Inside it, Playwright calls are Playwright's own, so
page.mouse.move in a move part moves the mouse once.

What is wrapped, per page, and the channel that drives it:

    mouse     Mouse.move / click / dblclick; Page/Frame/Locator click, dblclick,
              hover, check and uncheck, and the click that focuses a field
              before fill
    keyboard  Keyboard.type / press; Page/Frame/Locator fill, type, press, and
              Locator.press_sequentially
    scroll    Mouse.wheel; Locator.scroll_into_view_if_needed, and the scroll
              into view before a pointer action, fill, type or
              press_sequentially

ElementHandle methods, tap, drag_and_drop and drag_to are Playwright's own. An
ElementHandle cannot be measured and moved to as a Locator can, and a drag's
moves happen inside Playwright's server.

Playwright runs an action inside its own server, so a client wrapper cannot
reach into it. The wrappers act first: myuri scrolls the element into view,
moves to the point and presses there, and Playwright's own action runs only
where myuri does not drive the channel.
"""

from __future__ import annotations

import asyncio
import inspect
import secrets
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Dict, Generator, Mapping, Optional, Tuple

from myuri import Actions, Missed, make_rng, profile_from_seed, run_async, run_sync
from myuri.page_functions import HIT_TEST_JS
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

from ._warnings import LeakWarning
from .driver_defaults import FILL_NEEDS_CLICK
from .humanize import Humanize, normalize

Flow = Generator[Any, Any, Any]

# True while a part of the caller's runs: its Playwright calls are Playwright's.
_IN_PART = ContextVar('camoufox_humanize_in_part', default=False)
# The timeout of the action running in this task, for the host's page reads.
_TIMEOUT: ContextVar[Optional[float]] = ContextVar('camoufox_humanize_timeout', default=None)

_SETUP = '_camoufox_humanize'
_ACTIONS = '_camoufox_actions'
_ROUTED_FRAMES = '_camoufox_humanize_routed'

_VIEWPORT = '() => [innerWidth, innerHeight]'
# The element's client origin in its frame, or null in the top window, whose
# viewport is the page's.
_FRAME_ORIGIN = 'e => { if (window === window.top) return null; const r = e.getBoundingClientRect(); return [r.x, r.y]; }'


class _Host:
    """myuri's host on one page: every event is a Playwright input call."""

    def __init__(self, page: Any, is_async: bool) -> None:
        self.page = page
        self.is_async = is_async
        mouse, keyboard = page.mouse, page.keyboard
        self.raw_move, self._down, self._up, self._wheel = mouse.move, mouse.down, mouse.up, mouse.wheel
        self._key_down, self._key_up, self._insert_text = keyboard.down, keyboard.up, keyboard.insert_text

    def run(self, flow: Flow) -> Any:
        return run_async(flow) if self.is_async else run_sync(flow)

    def move(self, x: float, y: float) -> Any:
        return self.raw_move(x, y)

    def click(self, button: str, click_count: int, hold_ms: float) -> Any:
        return self.run(self._click(button, click_count, hold_ms))

    def _click(self, button: str, click_count: int, hold_ms: float) -> Flow:
        yield self._down(button=button, click_count=click_count)
        yield self.sleep(hold_ms)
        yield self._up(button=button, click_count=click_count)

    def down(self, button: str) -> Any:
        return self._down(button=button)

    def up(self, button: str) -> Any:
        return self._up(button=button)

    def wheel(self, dx: float, dy: float) -> Any:
        return self._wheel(dx, dy)

    def key_down(self, key: str) -> Any:
        return self._key_down(key)

    def key_up(self, key: str) -> Any:
        return self._key_up(key)

    def insert_text(self, text: str) -> Any:
        return self._insert_text(text)

    def evaluate(self, target: Any, fn: str, arg: Any) -> Any:
        return target.evaluate(fn, arg, timeout=_TIMEOUT.get())

    def offset(self, target: Any) -> Any:
        return self.run(self._offset(target))

    def _offset(self, target: Any) -> Flow:
        timeout = _TIMEOUT.get()
        origin = yield target.evaluate(_FRAME_ORIGIN, timeout=timeout)
        if origin is None:
            return (0, 0)
        box = yield target.bounding_box(timeout=timeout)
        return None if box is None else (box['x'] - origin[0], box['y'] - origin[1])

    def viewport(self) -> Any:
        return self.page.evaluate(_VIEWPORT)

    def now(self) -> float:
        return time.monotonic() * 1000

    def sleep(self, ms: float) -> Any:
        return asyncio.sleep(ms / 1000) if self.is_async else time.sleep(ms / 1000)


# ---- parts -------------------------------------------------------------------

def _raw_move(host: _Host, x: float, y: float, *, play: Any, **_: Any) -> Any:
    return play([('move', x, y, 0)])


def _raw_into_view(host: _Host, target: Any, **_: Any) -> Any:
    return _locator_original(target, 'scroll_into_view_if_needed')(target, timeout=_TIMEOUT.get())


# What myuri calls for a raw() channel: the parts its other channels' flows use.
_RAW_PARTS: Dict[str, Dict[str, Callable[..., Any]]] = {
    'mouse': {'move': _raw_move},
    'keyboard': {},
    'scroll': {'into_view': _raw_into_view},
}


def _callers_part(fn: Callable[..., Any], page: Any, is_async: bool) -> Callable[..., Any]:
    """A part passed to myuri(), called with the page in place of the host."""
    if is_async:
        async def part(host: _Host, *args: Any, **kwargs: Any) -> Any:
            token = _IN_PART.set(True)
            try:
                result = fn(page, *args, **kwargs)
                return (await result) if inspect.isawaitable(result) else result
            finally:
                _IN_PART.reset(token)
    else:
        def part(host: _Host, *args: Any, **kwargs: Any) -> Any:
            token = _IN_PART.set(True)
            try:
                return fn(page, *args, **kwargs)
            finally:
                _IN_PART.reset(token)

    return part


class _Setup:
    """The humanize setting of one browser: its engines, its stream, and its API."""

    def __init__(self, engines: Mapping[str, Any], seed: int, settings: Mapping[str, Any], os: str, is_async: bool) -> None:
        self.engines = dict(engines)
        self.os = os
        self.is_async = is_async
        # One stream for every page, so two pages never replay the same draws.
        self.rng = make_rng(seed)
        # One person for the whole browser, drawn from the seed around the
        # settings. Camoufox identities point with a mouse unless told otherwise.
        scroll = {'device': 'mouse', **(settings.get('scroll') or {})}
        self.settings = profile_from_seed(seed, {**settings, 'scroll': scroll}, os)

    def drives(self, channel: str) -> bool:
        """Whether myuri drives the channel for the call being made."""
        return self.engines[channel]['engine'] == 'myuri' and not _IN_PART.get()

    def actions(self, page: Any) -> Actions:
        parts: Dict[str, Callable[..., Any]] = {}
        for channel, engine in self.engines.items():
            if engine['engine'] == 'raw':
                parts.update(_RAW_PARTS[channel])
            else:
                parts.update({name: _callers_part(fn, page, self.is_async)
                              for name, fn in engine['options'].items()})
        return Actions(
            _Host(page, self.is_async), self.rng, os=self.os, settings=self.settings,
            asynchronous=self.is_async, parts=parts,
        )


# ---- flows -------------------------------------------------------------------

def _timed(timeout: Optional[float], flow: Flow) -> Flow:
    token = _TIMEOUT.set(timeout)
    try:
        return (yield from flow)
    finally:
        _TIMEOUT.reset(token)


def _locator_original(locator: Any, name: str) -> Callable[..., Any]:
    return _LOCATOR_ORIGINALS[type(locator)][name]


def _timeout_of(locator: Any, params: Mapping[str, Any]) -> float:
    timeout = params.get('timeout')
    return locator.page._impl_obj._timeout_settings.timeout() if timeout is None else timeout


def _reach(actions: Actions, locator: Any, name: str, params: Mapping[str, Any], timeout: float) -> Flow:
    """myuri's click (or, for hover, its move) onto the locator, as Playwright's
    action fails: a timeout naming why the point was never reached."""
    try:
        yield from actions.click(
            locator,
            button=params.get('button') or 'left',
            click_count=params.get('click_count') or (2 if name == 'dblclick' else 1),
            modifiers=params.get('modifiers') or (),
            position=params.get('position'),
            force=bool(params.get('force')),
            press=name != 'hover',
            # 0 is no timeout, as in Playwright.
            timeout=timeout,
        )
    except Missed as missed:
        raise PlaywrightTimeoutError(f'Timeout {timeout:g}ms exceeded: {name} {missed}') from None


def _pointer(setup: _Setup, actions: Actions, locator: Any, original: Callable[..., Any],
             params: Dict[str, Any], name: str) -> Optional[Flow]:
    """click / dblclick / hover / check / uncheck."""
    if params.get('trial') or not (setup.drives('mouse') or setup.drives('scroll')):
        return None
    timeout = _timeout_of(locator, params)

    def flow() -> Flow:
        if not setup.drives('mouse'):
            yield from actions.into_view(locator)
            return (yield original(locator, **params))
        checkbox = name in ('check', 'uncheck')
        if checkbox and (yield locator.is_checked(timeout=timeout)) == (name == 'check'):
            return None
        yield from _reach(actions, locator, name, params, timeout)
        if checkbox and (yield locator.is_checked(timeout=timeout)) != (name == 'check'):
            raise RuntimeError(f'Clicking the checkbox did not change its state ({name})')
        return None

    return _timed(timeout, flow())


def _click_to_focus(setup: _Setup, actions: Actions, locator: Any, params: Mapping[str, Any]) -> Flow:
    """The click before a fill (driver_defaults), with myuri's move when it
    drives the mouse. The fill then finds the field focused."""
    timeout = _timeout_of(locator, params)
    if not (yield locator.evaluate(FILL_NEEDS_CLICK, timeout=timeout)):
        return
    yield from actions.into_view(locator)
    if (yield locator.evaluate(HIT_TEST_JS, None, timeout=timeout)) is not None:
        return
    if setup.drives('mouse'):
        yield from _reach(actions, locator, 'click', {'force': params.get('force')}, timeout)
    else:
        yield _locator_original(locator, 'click')(locator, timeout=timeout, force=params.get('force'))


def _keys(kind: str, text_param: str) -> Callable[..., Optional[Flow]]:
    """fill / type / press_sequentially / press on a locator."""

    def make(setup: _Setup, actions: Actions, locator: Any, original: Callable[..., Any],
             params: Dict[str, Any]) -> Optional[Flow]:
        keyboard, scroll = setup.drives('keyboard'), setup.drives('scroll') and kind != 'press'
        mouse = setup.drives('mouse') and kind == 'fill'
        if not (keyboard or mouse or scroll):
            return None
        text = params[text_param]

        def flow() -> Flow:
            if scroll:
                yield from actions.into_view(locator)
            if kind == 'fill':
                yield from _click_to_focus(setup, actions, locator, params)
            if not keyboard or text == '':
                return (yield original(locator, **params))
            timeout = params.get('timeout')
            if kind == 'fill':
                # Typing then replaces what the field held, as fill() does.
                yield locator.select_text(force=params.get('force'), timeout=timeout)
            else:
                yield locator.focus(timeout=timeout)
            return (yield from (actions.key(text) if kind == 'press' else actions.type(text)))

        return _timed(params.get('timeout'), flow())

    return make


def _scroll_locator(setup: _Setup, actions: Actions, locator: Any, original: Callable[..., Any],
                    params: Dict[str, Any]) -> Optional[Flow]:
    if not setup.drives('scroll'):
        return None
    return _timed(params.get('timeout'), actions.into_view(locator))


def _pointing(name: str) -> Callable[..., Optional[Flow]]:
    return lambda setup, actions, locator, original, params: _pointer(setup, actions, locator, original, params, name)


_LOCATOR_FLOWS: Dict[str, Callable[..., Optional[Flow]]] = {
    'click': _pointing('click'),
    'dblclick': _pointing('dblclick'),
    'hover': _pointing('hover'),
    'check': _pointing('check'),
    'uncheck': _pointing('uncheck'),
    'fill': _keys('fill', 'value'),
    'type': _keys('type', 'text'),
    'press_sequentially': _keys('type', 'text'),
    'press': _keys('press', 'key'),
    'scroll_into_view_if_needed': _scroll_locator,
}
_LOCATOR_ORIGINALS: Dict[type, Dict[str, Callable[..., Any]]] = {}


def _patch_locator_class(cls: type) -> None:
    """Route a Locator class's input methods through myuri on the locator's
    page. A page with no humanize setting (any other browser) gets the original."""
    if cls in _LOCATOR_ORIGINALS:
        return
    originals = _LOCATOR_ORIGINALS[cls] = {name: getattr(cls, name) for name in _LOCATOR_FLOWS}

    for name, original in originals.items():
        def make(name: str, original: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(original)
            def method(self: Any, *args: Any, **kwargs: Any) -> Any:
                setup: Optional[_Setup] = getattr(self.page, _SETUP, None)
                if setup is None:
                    return original(self, *args, **kwargs)
                params = dict(inspect.signature(original).bind(self, *args, **kwargs).arguments)
                params.pop('self', None)
                actions: Actions = getattr(self.page, _ACTIONS)
                flow = _LOCATOR_FLOWS[name](setup, actions, self, original, params)
                return original(self, **params) if flow is None else actions.run(flow)

            return method

        setattr(cls, name, make(name, original))


# Page and Frame methods that take a selector, routed to the Locator method of
# the same name when myuri drives one of these channels.
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


def _myuri_on(setup: _Setup, channels: Tuple[str, ...]) -> bool:
    return any(setup.engines[channel]['engine'] == 'myuri' for channel in channels)


def _attach_page(page: Any, setup: _Setup) -> None:
    if getattr(page, _SETUP, None) is not None:
        return
    actions = setup.actions(page)
    host: _Host = actions.host
    setattr(page, _ACTIONS, actions)
    setattr(page, _SETUP, setup)
    _patch_locator_class(type(page.locator('html')))
    mouse, keyboard = page.mouse, page.keyboard
    raw_click, raw_dblclick, raw_type, raw_press = mouse.click, mouse.dblclick, keyboard.type, keyboard.press

    @wraps(host.raw_move)
    def move(x: float, y: float, **kwargs: Any) -> Any:
        if setup.drives('mouse'):
            return actions.run(actions.move(x, y))
        actions.moved(x, y)
        return host.raw_move(x, y, **kwargs)

    def clicking(original: Callable[..., Any], double: bool) -> Callable[..., Any]:
        @wraps(original)
        def click(x: float, y: float, **kwargs: Any) -> Any:
            if not setup.drives('mouse'):
                actions.moved(x, y)
                return original(x, y, **kwargs)
            count = 2 if double else kwargs.get('click_count') or 1
            return actions.run(actions.click_at(x, y, kwargs.get('button') or 'left', count))

        return click

    def driven(channel: str, original: Callable[..., Any], flow: Callable[..., Flow]) -> Callable[..., Any]:
        @wraps(original)
        def method(*args: Any, **kwargs: Any) -> Any:
            return actions.run(flow(*args, **kwargs)) if setup.drives(channel) else original(*args, **kwargs)

        return method

    mouse.move = move
    mouse.click = clicking(raw_click, False)
    mouse.dblclick = clicking(raw_dblclick, True)
    # A delay is myuri's to plan.
    mouse.wheel = driven('scroll', host._wheel, lambda delta_x, delta_y: actions.wheel(delta_x, delta_y))
    keyboard.type = driven('keyboard', raw_type, lambda text, delay=None: actions.type(text))
    keyboard.press = driven('keyboard', raw_press, lambda key, delay=None: actions.key(key))

    # page.click(selector) and friends: the same flow as the locator's.
    for name, channels in _PAGE_ROUTES.items():
        if _myuri_on(setup, channels):
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
    page where myuri drives one of the channels."""
    if _ROUTED_FRAMES in cls.__dict__:
        return
    setattr(cls, _ROUTED_FRAMES, True)
    for name, channels in _PAGE_ROUTES.items():
        def make(original: Callable[..., Any], name: str, channels: Tuple[str, ...]) -> Callable[..., Any]:
            @wraps(original)
            def method(self: Any, *args: Any, **kwargs: Any) -> Any:
                setup: Optional[_Setup] = getattr(self.page, _SETUP, None)
                if setup is None or not _myuri_on(setup, channels):
                    return original(self, *args, **kwargs)
                return _routed(original.__get__(self), self, name)(*args, **kwargs)

            return method

        setattr(cls, name, make(getattr(cls, name), name, channels))


def _attach_context(context: Any, setup: _Setup) -> None:
    if getattr(context, _SETUP, None) is not None:
        return
    setattr(context, _SETUP, setup)
    context.on('page', lambda page: _attach_page(page, setup))
    for page in context.pages:
        _attach_page(page, setup)


def _is_async(target: Any) -> bool:
    from playwright._impl._async_base import AsyncBase

    return isinstance(target, AsyncBase)


def check(humanize: Any, is_async: bool) -> Humanize:
    """Check a `humanize` setting before a launch, and normalize it."""
    checked = normalize(humanize)
    if not is_async:
        for channel, engine in checked.engines.items():
            for name, fn in engine['options'].items():
                if inspect.iscoroutinefunction(fn):
                    raise ValueError(
                        f'humanize["{channel}"]: myuri({name}={getattr(fn, "__name__", fn)}) is async, but this '
                        'is the sync API. Pass a plain function, or use AsyncCamoufox.'
                    )
    return checked


def attach(
    target: Any,
    humanize: Any,
    os: str,
    i_know_what_im_doing: Optional[bool] = None,
    is_async: Optional[bool] = None,
) -> Any:
    """
    Run myuri on every page of `target`, a Browser or BrowserContext, including
    pages and contexts opened later, as the `humanize` setting says. Other
    browsers in this process are untouched. `os` ('macos', 'windows' or
    'linux') is the launch identity's, whose people myuri plans for.

    Every draw comes from one stream, of `humanize["seed"]` or a random seed,
    and the seed draws the person myuri plays around `humanize["settings"]`.
    """
    if is_async is None:
        is_async = _is_async(target)
    engines, seed, settings = check(humanize, is_async)
    if all(engine['engine'] == 'raw' for engine in engines.values()):
        return target
    if getattr(target, _SETUP, None) is not None:
        raise ValueError('humanize is already attached to this browser')
    impl = getattr(target, '_impl_obj', None)
    if getattr(getattr(impl, '_connection', None), 'is_remote', False):
        LeakWarning.warn('humanize_remote', i_know_what_im_doing)

    setup = _Setup(engines, secrets.randbits(32) if seed is None else seed, settings, os, is_async)

    if not hasattr(target, 'new_context'):
        # A BrowserContext (a persistent context).
        _attach_context(target, setup)
        return target

    setattr(target, _SETUP, setup)
    for context in target.contexts:
        _attach_context(context, setup)

    def on_context(context: Any) -> Any:
        _attach_context(context, setup)
        return context

    def on_page(page: Any) -> Any:
        _attach_context(page.context, setup)
        _attach_page(page, setup)
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
