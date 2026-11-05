# Humanized input: engines and `humanize-engines.json`

`humanize` picks an engine per input channel (`mouse`, `keyboard`, `scroll`).
The browser applies it to the Juggler input commands Playwright already sends,
so the same Playwright script drives every build, humanized or not. This page
is for whoever adds an engine to a build. The user-facing API is in the README
("Choosing an engine per channel").

## Where it runs

`browser/additions/juggler/input/HumanizeSeam.js` is the only place that knows about
engines. `PageHandler` asks it for a plan at five command sites:

| Command | Engine method | Channel |
|---|---|---|
| `Page.dispatchMouseEvent` `mousemove` | `planMove(ctx, to)` | mouse |
| `Page.dispatchWheelEvent` | `planWheel(ctx, at, {deltaX, deltaY, deltaZ})` | scroll |
| `Page.scrollIntoViewIfNeeded` | `planIntoView(ctx, probe)`, in rounds | scroll |
| `Page.dispatchKeyEvent` | `planKey(ctx, keyEvent)` | keyboard |
| `Page.insertText` | `planInsert(ctx, text)` | keyboard |

A `null` plan, a `raw` channel, or an engine without that method leaves the
stock dispatch in charge, byte for byte.

## Writing an engine

An engine is an object exported under its own name from an ES module that
Juggler can import. Its methods are pure planners. They return
`{steps, endState}` or `null` to decline. Each step carries `t`, the time in
ms from the start of the action, and the values in `t` never decrease. The step
kinds are:

- `move` (`x`, `y`)
- `wheel` (`x`, `y`, `dx`, `dy`, `dz`, `mode`, `ticks`)
- `key` (`type`, `key`, `code`, `keyCode`, `location`, `text`)
- `text` (`text`)
- `probe` (`planIntoView` only, last): measure again and plan another round

A move plan ends exactly on its target.

`ctx` holds:

- `rng`: the channel's seeded stream, the only randomness a planner may use.
- `options`: the engine's options, read from their config keys.
- `budgetMs`: the time the plan must fit in.
- `seed`: the launch's 64-bit seed.
- `now`: the time the action was planned at (ms, monotonic). A keyboard engine
  paces a keydown against the previous one on the page with it, so the time
  the client spent between two commands is absorbed rather than added.
- `cursor`, `viewport` and `keyboardState`: per-page state. `keyboardState` is
  one object per page that a keyboard engine may keep its own state in.
- `focus` (keyboard, on keydowns and `insertText`): the focused element as
  `{editable, multiline, type, maxLength}`. `editable` is true for a text
  `input`, a `textarea` or a contenteditable host that accepts input.

A planner reads no clock other than `ctx.now`, and uses no `Math.random`.
Everything it draws from `ctx.rng` must not depend on `ctx.now`, so a seeded
session draws the same numbers however late its commands arrive.

An engine can also define two optional methods:

- `available(channel)`: return `false` when the engine cannot run on that
  channel right now. `auto` then skips it, and an explicit request for it falls
  back with a warning. An engine listed on several channels can be ready on
  some of them only.
- `budgetMs(options)`: the engine's own time budget. Without it, the budget is
  the `budgetSeconds` option, or 8 s by default.

The seam plays plans with `Pacer.js`: every step is due at `start + t`, so a
slow ack delays only its own step. A plan over its budget is compressed. One
still playing past 1.5x its budget fast-forwards: it skips the remaining waits
and every step not marked `essential: true`, but always dispatches the last
step. An engine that throws falls back to the channel's last `auto` choice.

### Scrolling into view

`Page.scrollIntoViewIfNeeded` (the scroll inside `click`, `hover` and `fill`)
runs in rounds when the scroll engine has `planIntoView`. Each round the page
reports a probe, the engine plans wheel steps from it, and the browser first
moves the cursor to the first wheel's position (with the `mouse:internal`
engine, a single `mousemove` when that is `raw`), then plays the wheels. A plan
that ends in a `probe` step asks for another round, up to 4. The stock scroll
always runs last: it does nothing when the element is already in view, and it
raises the same errors as without an engine. The probe, in top-level viewport
CSS pixels:

| Field | Meaning |
|---|---|
| `targetRect` | The element (or the requested rect within it), or `null` when it cannot be scrolled to. |
| `clip` | The band the element can be seen in: the viewport inset by 20 px (10 px at the sides), minus fixed or sticky bars at the element's column, intersected with each scrollable ancestor. |
| `region` | The element's visible part of `clip`, or `null`. |
| `hitTestable`, `occluder` | Whether a fixed or sticky element covers `region` (hit-tested at five points), and its rect. |
| `scrollers` | The ancestors that can move the element, innermost first, then the page if it can: `{isPage, rect, band, scrollTop, maxScroll, wheelPoint: {down, up}}`, where `rect` is the scroller's box (`null` for the page) and `band` the part of it that is visible. `wheelPoint` is the point nearest the cursor from which a wheel in that direction scrolls this scroller rather than one inside it. |
| `viewport` | `{width, height}`. |

`ctx.round` is the round number, from 0.

## Engines outside the browser: `custom()`

A `custom(fn)` channel is not an engine in this sense. The launcher writes
`raw` for that channel, so the seam leaves Playwright's commands alone, and
wraps Playwright's input methods on the client instead
(`python/src/camoufox/_humanize_custom.py`, `typescript/src/humanize-custom.ts`).
User code never runs in the browser. A custom mouse also writes
`humanize:mouse:internal=auto`, so the moves the seam originates itself, like
the cursor move before a planned scroll, still get the build's mouse engine.
The browser guard is `browser/tests/playwright/patches/humanize-custom.py`.

## `humanize-engines.json`

Each build ships one beside `properties.json`. `browser/settings/humanize-engines.json`
is this repository's:

```json
{
  "version": 1,
  "mouse": ["raw", "cursory"],
  "keyboard": ["raw"],
  "scroll": ["raw", "notches"],
  "auto": {"mouse": ["cursory"], "keyboard": ["raw"], "scroll": ["notches"]},
  "engines": {
    "cursory": {
      "module": "resource://gre/modules/juggler/input/CursorTrajectory.js",
      "options": {
        "maxTime": {"key": "humanize:maxTime", "min": 0},
        "minTime": {"key": "humanize:minTime", "min": 0}
      }
    },
    "notches": {"module": "resource://gre/modules/juggler/input/WheelNotches.js"}
  }
}
```

| Field | Meaning |
|---|---|
| `mouse` / `keyboard` / `scroll` | The engines the channel may name. `raw` is always allowed. |
| `auto` | What `auto()` tries, in order: the first engine whose `available()` is not `false`. The last entry is the fallback for a failed or unavailable engine. |
| `engines.<name>.module` | The chrome URL of the module that exports the engine as `<name>`. |
| `engines.<name>.options` | Option name → `{key, min, max}`. The launchers accept only these options, check the range (`min` defaults to 0), and write each one as a double under `key`. The browser hands them to the engine as `ctx.options`. |
| `engines.<name>.movesCursor` | The scroll engine moves the cursor before it scrolls. With a `raw()` mouse, the launcher warns that the move is a jump. |

To add an engine to a build, package its module in a `jar.mn`, add its entry
and its channels to the build's `humanize-engines.json`, and declare its option
keys in `properties.json`. Neither the seam nor the launchers change.

A binary without the file predates per-channel humanize. The launchers then
write only `humanize` and `humanize:maxTime`/`minTime`, and refuse a setting
that such a binary cannot run.

## Seeds and the trace

`humanize:seed` is a decimal uint64 string, because Juggler reads config numbers
only as doubles. Each channel's stream is
`Mulberry32(splitmix64(seed ^ tag) & 0xffffffff)`, with tags `0x6d6f7573`
(mouse), `0x6b657962` (keyboard) and `0x7363726f` (scroll). Without a seed, each
launch draws a random one.

The launchers derive the same streams for `custom()` engines
(`channel_stream` in `python/src/camoufox/humanize.py`, `channelStream` in
`typescript/src/humanize.ts`). `browser/tests/humanize/rng-vectors.json` is written
from `HumanizeRng.js` by `browser/tests/juggler/gen-rng-vectors.mjs`, and all three
implementations are tested against it: change the derivation in all three or
in none.

With `CAMOU_HUMANIZE_TRACE=<file>` in the browser's environment, the seam
appends one JSON line per humanized action with these fields:

- `channel`, `engine`, `command`
- `seedStreamPos`, `budgetMs`
- `plan`
- `dispatched`: `[{i, tPlanned, tActual}]`
- `outcome`

The unit tests are in `browser/tests/juggler/` (`node --test browser/tests/juggler/*.test.mjs`),
and the browser guard is `browser/tests/playwright/patches/humanize-seam.py`.
