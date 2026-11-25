"""
Per-channel humanized input, run by the driver, never by the browser.

    from camoufox.humanize import myuri, raw

    Camoufox(humanize=True)                     # myuri on every channel
    Camoufox(humanize={
        "mouse": myuri(move=my_move),
        "scroll": raw(),
        "settings": {"typing": {"wpm": 70}},
        "seed": 1234,
    })

The browser has no humanization of its own: each Playwright input call reaches
the page as the one native-looking event (or click, or key) it asks for, when
it is sent (docs/input-dispatch.md). How a person moves, types and scrolls is
the driver's job. A channel (mouse, keyboard, scroll) is one of

    myuri()     myuri's smart actions (https://github.com/JWriter20/Myuri):
                paths, clicks, typing and wheel turns as the people it was
                fitted to make them on the identity's OS, and the decisions
                around a click (scroll into view, the point, whether it lands)
    raw()       Playwright's own calls, unchanged

cursory() is another name for myuri(), which runs cursory's paths.

`myuri(**parts)` replaces any of myuri's parts on its channel with a function
of yours; the rest stay myuri's (camoufox._humanize_playwright).

`humanize` may be None / False (every channel raw), True (every channel myuri),
or a dict per channel plus an optional "seed" and "settings"; an omitted
channel is myuri. "settings" are myuri's (its README lists each one), and the
seed draws one person around them. Nothing about it reaches the browser's
config.
"""

from typing import Any, Dict, Mapping, NamedTuple, Optional, Tuple, Union

from myuri import resolve_settings

CHANNELS = ('mouse', 'keyboard', 'scroll')

# The myuri parts each channel's myuri() may replace (myuri.PARTS).
CHANNEL_PARTS = {
    'mouse': ('move', 'press', 'point', 'reaches'),
    'keyboard': ('type', 'key'),
    'scroll': ('into_view', 'wheel'),
}

Engine = Dict[str, Any]
HumanizeSetting = Union[None, bool, Mapping[str, Any]]


def raw() -> Engine:
    """Playwright's own dispatch, byte for byte."""
    return {'engine': 'raw', 'options': {}}


def myuri(**options: Any) -> Engine:
    """
    myuri's smart actions on the channel. Each keyword names a part to replace
    with your function, called as `fn(page, *args, default, rng, play)`:

        mouse     move(x, y)  press(button, click_count)  point(box, attempt)
                  reaches(locator, x, y, pressing)
        keyboard  type(text)  key(key)
        scroll    into_view(locator)  wheel(dx, dy)

    `default(*args)` runs myuri's part (with the same arguments when given
    none), `rng()` draws from the humanize seed's stream, and `play(steps)`
    plays a timeline of input. With the async API each returns an awaitable,
    and the part may be async. Speeds and the like are `humanize["settings"]`.
    """
    unknown = set(options) - {part for parts in CHANNEL_PARTS.values() for part in parts}
    if unknown:
        raise ValueError(f'myuri() has no part {sorted(unknown)[0]!r}; the parts are {CHANNEL_PARTS} '
                         '(speeds and the like are humanize["settings"])')
    for name, fn in options.items():
        if not callable(fn):
            raise ValueError(f'myuri({name}=...) takes the function that replaces the part, got {fn!r}')
    return {'engine': 'myuri', 'options': dict(options)}


cursory = myuri


_IN_BROWSER = (
    'the browser does not humanize input: each Playwright call is one event. '
    'Pass True, or myuri() or raw() per channel (camoufox.humanize)'
)


def _as_engine(channel: str, value: Any) -> Engine:
    if not isinstance(value, Mapping) or value.get('engine') not in ('myuri', 'cursory', 'raw'):
        raise ValueError(f'humanize["{channel}"]={value!r} is not an engine; {_IN_BROWSER}')
    options = value.get('options') or {}
    if value['engine'] == 'raw':
        if options:
            raise ValueError(f'humanize["{channel}"]: raw() takes no options')
        return raw()
    engine = myuri(**options)
    misplaced = sorted(set(options) - set(CHANNEL_PARTS[channel]))
    if misplaced:
        raise ValueError(f'humanize["{channel}"]: myuri({misplaced[0]}=...) is not a {channel} part; '
                         f'the {channel} parts are {CHANNEL_PARTS[channel]}')
    return engine


class Humanize(NamedTuple):
    """A checked `humanize` setting."""

    engines: Dict[str, Engine]
    seed: Optional[int]
    settings: Dict[str, Any]


def normalize(humanize: HumanizeSetting) -> Humanize:
    """The engine per channel of a `humanize` setting, the seed (None when not
    given) and myuri's settings ({} when not given)."""
    if humanize is None or humanize is False:
        return Humanize({channel: raw() for channel in CHANNELS}, None, {})
    if humanize is True:
        return Humanize({channel: myuri() for channel in CHANNELS}, None, {})
    if not isinstance(humanize, Mapping):
        raise ValueError(f'humanize={humanize!r}: {_IN_BROWSER}')
    unknown = set(humanize) - {*CHANNELS, 'seed', 'settings'}
    if unknown:
        raise ValueError(f'humanize has no channel {sorted(unknown)}; '
                         f'the channels are {CHANNELS}, and "seed" and "settings"')
    seed = humanize.get('seed')
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32):
        raise ValueError(f'humanize["seed"] must be an integer in [0, 2**32), got {seed!r}')
    settings = humanize.get('settings') or {}
    if not isinstance(settings, Mapping):
        raise ValueError(f'humanize["settings"] must be a dict of myuri settings, got {settings!r}')
    try:
        resolve_settings(dict(settings))
    except KeyError as e:
        raise ValueError(f'humanize["settings"]: {e.args[0]}') from None
    engines = {channel: _as_engine(channel, humanize.get(channel, myuri())) for channel in CHANNELS}
    return Humanize(engines, seed, dict(settings))


def attach(
    target: Any, humanize: HumanizeSetting, os: str, i_know_what_im_doing: Optional[bool] = None
) -> Any:
    """
    Run the engines of `humanize` on a Browser or BrowserContext that camoufox
    did not launch in this process, e.g. one from `connect()`. Launch that
    browser without humanize; `os` ('macos', 'windows' or 'linux') is its
    identity's. Camoufox()/NewBrowser() call this themselves.
    """
    from ._humanize_playwright import attach as attach_engines

    return attach_engines(target, humanize, os, i_know_what_im_doing=i_know_what_im_doing)


def driven_channels(humanize: HumanizeSetting) -> Tuple[str, ...]:
    """The channels of a `humanize` setting that an engine in this process drives."""
    engines = normalize(humanize).engines
    return tuple(channel for channel in CHANNELS if engines[channel]['engine'] != 'raw')
