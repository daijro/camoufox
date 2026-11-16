# Humanized input lives in the driver

The browser does not humanize input. Each Juggler input command Playwright sends
becomes one event of the shape a real device gives stock Firefox
([input-dispatch.md](input-dispatch.md) has each shape per OS), and the browser adds
no paths, pacing, splitting or randomness of its own. Whatever makes input look
human (the path a cursor takes, the times between keys, how a wheel turn is
broken into strokes) is planned in the process that drives the browser and sent as
ordinary Playwright calls.

This keeps the two jobs apart. The browser's job is that one call looks like one
real event; the driver's job is that the sequence of events looks like a person.
A driver that humanizes on its own (a cursor or typing library) gets exactly the
events it sends, never a second layer of delays on top of its own.

## What the launchers keep

`humanize` is still a launch option in both launchers, for driver-side engines:

```python
from camoufox.humanize import custom, raw

humanize = {"mouse": custom(my_move), "keyboard": raw(), "scroll": raw(), "seed": 1234}
```

- Each channel (`mouse`, `keyboard`, `scroll`) is `raw()` (Playwright as it is) or
  `custom(fn)`. An omitted channel is `raw()`, and so is `humanize=None` or `False`.
- `humanize=True`, a number, an engine name, or a dict naming any other engine is
  refused with an error saying the browser no longer humanizes. Before this
  change those turned on the browser's own cursor paths and wheel pacing.
- Nothing about humanize reaches the browser's config. The `humanize*` keys are
  marked `removed` in `browser/settings/properties.json`.

`custom(fn)` wraps Playwright's input methods on the client
(`python/src/camoufox/_humanize_custom.py`, `typescript/src/_humanize_custom.ts`);
the README's "Writing your own engine" has the call signatures. User code never
runs in the browser. The browser guard is
`browser/tests/playwright/patches/humanize-custom.py`.

## Seeds

`seed` (an integer below 2^64) seeds one stream per channel, passed to a custom
function as `rng`. Each stream is `Mulberry32(splitmix64(seed ^ tag) & 0xffffffff)`,
with tags `0x6d6f7573` (mouse), `0x6b657962` (keyboard) and `0x7363726f` (scroll)
(`channel_stream` in `python/src/camoufox/humanize.py`, `channelStream` in
`typescript/src/humanize.ts`). `browser/tests/humanize/rng-vectors.json` pins the
draws, and both launchers are tested against it: change the derivation in both or
in neither. Without a seed, each launch draws a random one.

## What the browser still times

Some single commands still carry timing inside the browser, because without it
one Playwright call would produce events no keyboard can:

- **Paste.** `fill()` and `keyboard.insert_text()` send `Page.insertText`, which
  Juggler turns into Ctrl+V (Cmd+V on a Mac identity) around Firefox's own paste.
  The modifier leads V by about 60 ms, V is held about 116 ms, and the modifier
  trails by about 40 ms. Without them the shortcut would go down and up in the
  same millisecond.
- **Shift for a shifted character.** A `keyboard.press("A")` or a typed `!` holds
  Shift around the key, with the same lead and trail.
- **A refused paste.** A page that cancels the paste gets the text typed key by
  key at a person's rate, as a person types what they cannot paste.

These are one command's own events, drawn in the content process from
`input/HumanDelay.js` with the figures input-dispatch.md cites; they never pace
one command against the next. Mouse moves are also sent at least 8 ms apart (a
125 Hz mouse's reports), which a driver pacing its moves at 8 ms or more never
sees.
