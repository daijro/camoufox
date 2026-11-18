"""
Per-channel humanized input, run by the driver, never by the browser.

    from camoufox.humanize import custom, myuri, raw

    Camoufox(humanize=True)                     # myuri on every channel
    Camoufox(humanize={
        "mouse": custom(my_mouse),
        "scroll": raw(),
        "seed": 1234,
    })                                          # keyboard: myuri

The browser has no humanization of its own: each Playwright input call reaches
the page as the one native-looking event (or click, or key) it asks for, when
it is sent (docs/input-dispatch.md). How a person moves, types and scrolls is
the driver's job. A channel (mouse, keyboard, scroll) is one of

    myuri()     paths, clicks, typing and wheel turns planned by myuri for the
                identity's OS
    custom(fn)  a function in this process plans the channel's input
    raw()       Playwright's own calls, unchanged

Both planners play through Playwright's own input methods, with schedule pacing
and a seeded stream (camoufox._humanize_custom).

`humanize` may be None / False (every channel raw), True (every channel myuri),
or a dict per channel plus an optional "seed"; an omitted channel is myuri.
Nothing about it reaches the browser's config.
"""

from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union

CHANNELS = ('mouse', 'keyboard', 'scroll')

Engine = Dict[str, Any]
HumanizeSetting = Union[None, bool, Mapping[str, Any]]


def raw() -> Engine:
    """Playwright's own dispatch, byte for byte."""
    return {'engine': 'raw', 'options': {}}


def myuri(**options: Any) -> Engine:
    """
    myuri (https://github.com/JWriter20/Myuri) plans the channel's input as the
    people it was fitted to move, click, type and scroll on the identity's OS.
    `options` go to its planner: `wpm` for the keyboard.
    """
    unknown = set(options) - {'wpm'}
    if unknown:
        raise ValueError(f'myuri() takes no option {sorted(unknown)}; it takes wpm')
    return {'engine': 'myuri', 'options': dict(options)}


def custom(fn: Callable[..., Any]) -> Engine:
    """
    A client-side engine: `fn` plans the channel's input in this process and
    plays it through Playwright. Its signature, per channel:

        mouse     fn(page, x, y, *, original, rng, play, click)
        keyboard  fn(page, text, *, original, rng, play, kind)   kind: 'type', 'press' or 'fill'
        scroll    fn(page, target, *, original, rng, play)       target: a Locator or (dx, dy)

    `original` runs Playwright's own behaviour for the call, `rng` is the
    channel's seeded stream, and `play(steps)` dispatches steps on a schedule.
    With the async API `fn` may be async.

    For a move, `click` is None. For a click it is a dict: `button`,
    `click_count`, and `box`, the element's box when the caller gave no point
    in it (`fn` may then press anywhere in it). `fn` moves, then presses with
    `original(x, y, delay=hold_ms)`: a mouse down and up at (x, y), moving there
    first only if the cursor is elsewhere. `delay` is how long each press is
    held, and between the presses of a double click. A point something covers
    raises inside `original()`, and `fn` is called again until the timeout.

    Each wheel step is one wheel event, in whole notches as a physical wheel
    turns: 100 px is one notch, rounded, at least one, all of a step's notches
    in that one event. A macOS identity turns in 16 px lines instead
    (docs/input-dispatch.md). A person's scroll is several steps.
    """
    if not callable(fn):
        raise ValueError(f'custom() takes the function that plans the input, got {fn!r}')
    return {'engine': 'custom', 'options': {}, 'fn': fn}


_IN_BROWSER = (
    'the browser does not humanize input: each Playwright call is one event. '
    'Pass True, or myuri(), custom(fn) or raw() per channel (camoufox.humanize)'
)


def _as_engine(channel: str, value: Any) -> Engine:
    if not isinstance(value, Mapping) or value.get('engine') not in ('myuri', 'custom', 'raw'):
        raise ValueError(f'humanize["{channel}"]={value!r} is not an engine; {_IN_BROWSER}')
    name, options = value['engine'], value.get('options') or {}
    if name == 'myuri':
        return myuri(**options)
    if options:
        raise ValueError(f'humanize["{channel}"]: {name}() takes no options')
    return custom(value.get('fn')) if name == 'custom' else raw()


def normalize(humanize: HumanizeSetting) -> Tuple[Dict[str, Engine], Optional[int]]:
    """The engine per channel of a `humanize` setting, and the seed (None when
    not given)."""
    if humanize is None or humanize is False:
        return {channel: raw() for channel in CHANNELS}, None
    if humanize is True:
        return {channel: myuri() for channel in CHANNELS}, None
    if not isinstance(humanize, Mapping):
        raise ValueError(f'humanize={humanize!r}: {_IN_BROWSER}')
    unknown = set(humanize) - {*CHANNELS, 'seed'}
    if unknown:
        raise ValueError(f'humanize has no channel {sorted(unknown)}; the channels are {CHANNELS} and "seed"')
    seed = humanize.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64):
        raise ValueError(f'humanize["seed"] must be an integer in [0, 2**64), got {seed!r}')
    engines = {channel: _as_engine(channel, humanize.get(channel, myuri())) for channel in CHANNELS}
    return engines, seed


def attach(
    target: Any, humanize: HumanizeSetting, os: str, i_know_what_im_doing: Optional[bool] = None
) -> Any:
    """
    Run the engines of `humanize` on a Browser or BrowserContext that camoufox
    did not launch in this process, e.g. one from `connect()`. Launch that
    browser without humanize; `os` ('macos', 'windows' or 'linux') is its
    identity's. Camoufox()/NewBrowser() call this themselves.
    """
    from ._humanize_custom import attach as attach_engines

    return attach_engines(target, humanize, os, i_know_what_im_doing=i_know_what_im_doing)


def driven_channels(humanize: HumanizeSetting) -> Tuple[str, ...]:
    """The channels of a `humanize` setting that an engine in this process drives."""
    engines, _seed = normalize(humanize)
    return tuple(channel for channel in CHANNELS if engines[channel]['engine'] != 'raw')


# The seeded streams, one per channel, the same in the TypeScript launcher:
#
#   stream(channel) = Mulberry32(splitmix64(seed ^ TAG[channel]) & 0xffffffff)

_MASK32 = 0xFFFFFFFF
_MASK64 = 0xFFFFFFFFFFFFFFFF
CHANNEL_TAGS = {'mouse': 0x6D6F7573, 'keyboard': 0x6B657962, 'scroll': 0x7363726F}


def splitmix64(x: int) -> int:
    """One splitmix64 output for the 64-bit state `x`."""
    z = ((x & _MASK64) + 0x9E3779B97F4A7C15) & _MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return z ^ (z >> 31)


class SeededRng:
    """
    Mulberry32 over a 32-bit seed. Calling it (or `random()`) returns a float
    in [0, 1), bit for bit what the TypeScript launcher's stream returns.
    """

    __slots__ = ('_a',)

    def __init__(self, seed32: int) -> None:
        self._a = seed32 & _MASK32

    def random(self) -> float:
        a = self._a = (self._a + 0x6D2B79F5) & _MASK32
        t = ((a ^ (a >> 15)) * (1 | a)) & _MASK32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _MASK32)) & _MASK32) ^ t
        return ((t ^ (t >> 14)) & _MASK32) / 4294967296

    __call__ = random


def channel_stream(seed: int, channel: str) -> SeededRng:
    """The stream a channel draws from for the 64-bit master `seed`."""
    tag = CHANNEL_TAGS.get(channel)
    if tag is None:
        raise ValueError(f'unknown humanize channel: {channel}')
    return SeededRng(splitmix64((seed & _MASK64) ^ tag) & _MASK32)
