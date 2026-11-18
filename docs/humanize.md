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

## The engines

`humanize` is a launch option in both launchers. Each channel (`mouse`,
`keyboard`, `scroll`) runs one engine in the driver process:

```python
from camoufox.humanize import custom, myuri, raw

humanize = {"mouse": myuri(), "keyboard": myuri(wpm=70), "scroll": raw(), "seed": 1234}
```

- `myuri()` is [myuri](https://github.com/JWriter20/Myuri), fitted to recordings
  of people on each OS ([`ci/tribal-rules.yml`](../ci/tribal-rules.yml), the
  `human-*` rules). It plans for the launch identity's OS, since input behaviour
  belongs to the browser, not the context. Both packages depend on it (PyPI
  `myuri`, npm `@jwriter20/myuri`), pinned to one release so a seed plans the
  same input in Python and TypeScript.
- `custom(fn)` runs your own function; the README's "Writing your own engine"
  has the call signatures.
- `raw()` is Playwright as it is.
- `humanize=True` is `myuri()` on every channel, and a channel a dict leaves out
  is `myuri()`. `humanize=None` or `False` (the default) is `raw()` everywhere.
- Nothing about humanize reaches the browser's config. The `humanize*` keys are
  marked `removed` in `browser/settings/properties.json`.

The engine owns timing and motion: the path, the dwell before a press, the hold,
the gaps between keys, Shift's lead and trail, and how a scroll is split into
wheel notches. The browser owns the shape of each event (deltaMode, wheelDelta,
coalescing, fractional coordinates), which a driver cannot set
([`humanize-timing-is-the-engine-and-shape-is-the-browser`](../ci/tribal-rules.yml)).

The engines wrap Playwright's input methods on the client
(`python/src/camoufox/_humanize_custom.py`, `_humanize_myuri.py`, and their
TypeScript counterparts). User code never runs in the browser. The browser
guard is `browser/tests/playwright/patches/humanize-custom.py`.

A humanized click is pressed by the wrapper, not by Playwright's click. The
engine moves the cursor and waits its dwell, and its `original()` sends a mouse
down and up where the cursor is, held for the engine's drawn hold. Playwright's
click would move again first, and the browser counts that move against the
next press's click count ([Click count](input-dispatch.md#click-count)).
Before pressing, the wrapper checks in the page's isolated world that the point
reaches the element: nothing covers it, and the element is enabled. A press
that would miss is planned again, with the engine called again, on Playwright's
retry schedule until the call's timeout. It then raises Playwright's
`TimeoutError`, naming what covers the point. Playwright's own wait for the
element to stop moving is not part of this check. `trial=True` and `force=True`
work as they do in Playwright: a trial click goes to Playwright alone, and a
forced click skips the check.

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

They are for raw Playwright. An engine that holds Shift itself, as myuri does,
gets no second Shift: Juggler skips its own when a real Shift is down. These are
one command's own events, drawn in the content process from
`input/HumanDelay.js` with the figures input-dispatch.md cites; they never pace
one command against the next. Mouse moves are also sent at least 8 ms apart (a
125 Hz mouse's reports), which a driver pacing its moves at 8 ms or more never
sees.
