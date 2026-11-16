"""
Per-channel humanized input, run by the driver, never by the browser.

    from camoufox.humanize import custom, raw

    Camoufox(humanize={
        "mouse": custom(my_mouse),
        "scroll": raw(),
        "seed": 1234,
    })

The browser has no humanization of its own: each Playwright input call reaches
the page as the one native-looking event (or click, or key) it asks for, when
it is sent (docs/input-dispatch.md). How a person moves, types and scrolls is
the driver's job. A channel (mouse, keyboard, scroll) is either

    raw()       Playwright's own calls, unchanged
    custom(fn)  a function in this process plans the channel's input and plays
                it through Playwright's own input methods, with schedule pacing
                and a seeded stream (camoufox._humanize_custom)

`humanize` itself may be None / False (every channel raw), or a dict per
channel plus an optional "seed"; an omitted channel is raw. Nothing about it
reaches the browser's config.
"""

from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union

CHANNELS = ('mouse', 'keyboard', 'scroll')

Engine = Dict[str, Any]
HumanizeSetting = Union[None, bool, Mapping[str, Any]]


def raw() -> Engine:
    """Playwright's own dispatch, byte for byte."""
    return {'engine': 'raw', 'options': {}}


def custom(fn: Callable[..., Any]) -> Engine:
    """
    A client-side engine: `fn` plans the channel's input in this process and
    plays it through Playwright. Its signature, per channel:

        mouse     fn(page, x, y, *, original, rng, play)
        keyboard  fn(page, text, *, original, rng, play, kind)   kind: 'type', 'press' or 'fill'
        scroll    fn(page, target, *, original, rng, play)       target: a Locator or (dx, dy)

    `original` runs Playwright's own behaviour for the call, `rng` is the
    channel's seeded stream, and `play(steps)` dispatches steps on a schedule.
    With the async API `fn` may be async.

    Each wheel step is one wheel event, in whole notches as a physical wheel
    turns: 100 px is one notch, rounded, at least one, all of a step's notches
    in that one event. A macOS identity turns in 16 px lines instead
    (docs/input-dispatch.md). A person's scroll is several steps.
    """
    if not callable(fn):
        raise ValueError(f'custom() takes the function that plans the input, got {fn!r}')
    return {'engine': 'custom', 'options': {}, 'fn': fn}


_IN_BROWSER = (
    'the browser no longer humanizes input: each Playwright call is one event. '
    'Humanize in the driver, with custom(fn) per channel (camoufox.humanize) or a driver-level library'
)


def _as_engine(channel: str, value: Any) -> Engine:
    candidate = {'engine': value, 'options': {}} if isinstance(value, str) else value
    if not isinstance(candidate, Mapping) or not isinstance(candidate.get('engine'), str):
        raise ValueError(f'humanize["{channel}"] must be raw() or custom(fn), got {value!r}')
    name = candidate['engine']
    if name == 'custom':
        if not callable(candidate.get('fn')):
            raise ValueError(f'humanize["{channel}"]: a custom engine needs its function, as custom(fn)')
        if candidate.get('options'):
            raise ValueError(f'humanize["{channel}"]: custom() takes no options; the function is the engine')
        return {'engine': 'custom', 'options': {}, 'fn': candidate['fn']}
    if name != 'raw':
        raise ValueError(f'humanize["{channel}"]: {name!r} is not an engine; {_IN_BROWSER}')
    if candidate.get('options'):
        raise ValueError(f'humanize["{channel}"]: raw() takes no options')
    return raw()


def normalize(humanize: HumanizeSetting) -> Tuple[Dict[str, Engine], Optional[int]]:
    """The engine per channel of a `humanize` setting, and the seed (None when
    not given)."""
    if humanize is None or humanize is False:
        return {channel: raw() for channel in CHANNELS}, None
    if not isinstance(humanize, Mapping):
        raise ValueError(f'humanize={humanize!r}: {_IN_BROWSER}')
    unknown = set(humanize) - {*CHANNELS, 'seed'}
    if unknown:
        raise ValueError(f'humanize has no channel {sorted(unknown)}; the channels are {CHANNELS} and "seed"')
    seed = humanize.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64):
        raise ValueError(f'humanize["seed"] must be an integer in [0, 2**64), got {seed!r}')
    engines = {channel: _as_engine(channel, humanize.get(channel, 'raw')) for channel in CHANNELS}
    return engines, seed


def attach_custom(target: Any, humanize: HumanizeSetting, i_know_what_im_doing: Optional[bool] = None) -> Any:
    """
    Run the custom() engines of `humanize` on a Browser or BrowserContext that
    camoufox did not launch in this process, e.g. one from `connect()`. Launch
    that browser with raw() on those channels. Camoufox()/NewBrowser() call this
    themselves.
    """
    from ._humanize_custom import attach

    return attach(target, humanize, i_know_what_im_doing=i_know_what_im_doing)


def custom_engines(humanize: HumanizeSetting) -> Dict[str, Callable[..., Any]]:
    """The functions of a `humanize` setting's custom channels, by channel."""
    engines, _seed = normalize(humanize)
    return {channel: engines[channel]['fn'] for channel in CHANNELS if engines[channel]['engine'] == 'custom'}


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
    in [0, 1), bit for bit what the browser's stream returns; `position`
    counts the draws.
    """

    __slots__ = ('_a', 'position')

    def __init__(self, seed32: int) -> None:
        self._a = seed32 & _MASK32
        self.position = 0

    def random(self) -> float:
        self.position += 1
        a = self._a = (self._a + 0x6D2B79F5) & _MASK32
        t = ((a ^ (a >> 15)) * (1 | a)) & _MASK32
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & _MASK32)) & _MASK32) ^ t
        return ((t ^ (t >> 14)) & _MASK32) / 4294967296

    __call__ = random

    def uniform(self, low: float, high: float) -> float:
        """low + (high - low) * one draw."""
        return low + (high - low) * self.random()


def channel_stream(seed: int, channel: str) -> SeededRng:
    """The stream a channel draws from for the 64-bit master `seed`."""
    tag = CHANNEL_TAGS.get(channel)
    if tag is None:
        raise ValueError(f'unknown humanize channel: {channel}')
    return SeededRng(splitmix64((seed & _MASK64) ^ tag) & _MASK32)
