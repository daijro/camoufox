# Synthesized input dispatch

Every synthesized mouse and wheel event in the parent process goes through
`browser/additions/juggler/input/MouseDispatch.js`.
`browser/scripts/check-input-dispatch.py` fails the build if anything else
dispatches input or does browser-relative coordinate arithmetic, and it runs on
every pull request.

## The invariant

> A synthesized input event whose ack we await must reach the content
> renderer — and when it does not, we must stop waiting.

## Why it is worth a module and a lint

Four deadlocks shipped between 2026-04 and 2026-09, all the same failure:

| Date | Commit | Trigger |
|---|---|---|
| 2026-06-04 | `9270618` | `x == width` / `y == height` — the far edges |
| 2026-07-18 | `541ffca` | trajectory points, which bypassed the endpoint's guard (#225, #677) |
| 2026-07-24 | `16e5a13` | a zero-displacement move |
| 2026-09-03 | `014cc65` | `y == 0` — the near edge (#751, #752) |

Each was fixed by adding one more coordinate guard at one more call site. That
does not converge, for two reasons.

**The trigger set is not enumerable.** Whether relative `y == 0` reaches the
renderer is decided by `Math.round(boundingBox.top) < boundingBox.top` — a
rounding accident in the fractional height of browser chrome, which varies with
the *spoofed OS*: windows `51.4` → `51` deadlocks, macos `53.1` → `53`
deadlocks, linux `56.5` → `57` is fine. No review catches that, and no
hand-written list of coordinates contains it.

**Every miss costs the whole process.** `activateAndRun()`
(`TargetRegistry.js`) serializes input on a promise chain shared by every tab in
the process. It swallows errors to keep the chain running, but it cannot swallow
a callback that never returns. One unbounded `await` for an ack that will never
arrive wedges every later input event, in every tab, permanently — at 0% CPU,
with nothing in flight and no diagnostic.

`#677` is why review is not enough: restoring the humanize trajectory meant
writing a bounds check, and the one written was a copy of the pre-`#225` form,
reintroducing a fixed deadlock one day before it was re-fixed.

## How it is enforced

**One chokepoint.** `MouseDispatch` owns the relative→absolute conversion (with
the boundary snap), the in-viewport predicate, and the ack wait. Callers pass
relative coordinates and never see a bounding box.

**A fresh rect.** The browser rect is measured *after* the last `await` before
the dispatch (`apz-repaints-flushed`), never before it. The chrome can change
height during that wait — measured 2026-09-14: the nav-bar grew from 40 to
41 px about a second after startup when the (then forced) built-in theme was
applied — and a rect taken before it put a relative `y == 0` one row above the
content: the event reached the renderer as an exit event at client `y == -1`,
produced no ack, and the page saw no mousemove (~1 in 25 runs of
`near-edge-mouse-deadlock.py`). Both dispatch sites (`Page.dispatchMouseEvent`,
`Page.dispatchWheelEvent`) measure synchronously before dispatching.

**Bounded waits.** `sendAcked()` waits at most `kAckDeadlineMs` (5s) and then
drops the event with a warning naming the type, coordinate and browser rect. The
deadline is sized above the slowest *legitimate* ack, not near the typical one:
acks are p99 1ms on an idle page, but they are delivered from the content main
thread and inherit any block on it — a 3s synchronous script delayed one by
2849ms. `sendTrajectoryAcked()` abandons the rest of a curve after the first
undelivered point, so the ~90 bounded waits a curve can hold — the 1.5s default
humanize ceiling at 60Hz — cannot add up to an unbounded slot. It also refuses
to dispatch a point on the pixel the previous dispatch left the cursor on: a
zero-displacement move produces no `eMouseMove`, so it is never acked, and
that is the same deadlock reached from inside a curve rather than from
`Page.dispatchMouseEvent`.
`apz-repaints-flushed` waits at most `kAckDeadlineMs` too: a flush sent to a
GPU process that dies never comes back, and stalled every such dispatch until
the backstop. So does the drag path's `juggler-drag-finalized`, per input
event: an answer a busy page gives later still decides the next event, so the
drag drops, and mouseup ends the wait. `activateAndRun()` carries a 30s
backstop for the waits still unbounded in the same slot (`TabSwitchDone`, the
drag path's `dragover` and cross-process sends), none of which has failed yet.

**The static check.** `browser/scripts/check-input-dispatch.py`, wired into the
`static` job of `.github/workflows/tests.yml`. Two exemptions, both
content-process: `PageAgent.js` (drag events, already content-relative, no ack)
and `FrameTree.js` (the ack *producer*).

**Boundary coverage.**
`browser/tests/playwright/patches/mouse-boundary-sweep.py` sweeps the whole
viewport ring across every spoofed OS with humanize on and off, asserting each
point is acked *and observed by the page*. Hand-picked coordinate lists are what
let each of the four bugs through: `humanize-edge-deadlock.py` probed only the
far edges, and `humanize-mouse-trajectory.py` pins `os="linux"` — the one
fingerprint immune to `#751`.
`browser/tests/playwright/patches/input-ack-backstop.py` covers the bounded waits
themselves: a late renderer ack, and a drag whose page answers late.

## Move coalescing

A real mouse reports moves faster than the refresh driver ticks. The content
process queues them (`CoalescedMouseData`) and, at the next tick, dispatches
one `pointermove`/`mousemove` that carries the queued moves in
`getCoalescedEvents()`. A `pointerrawupdate` is dispatched for each move as it
arrives. Juggler's moves used to skip that queue, so each one reached the page
by itself: one `pointermove` per move, a coalesced list of length 1, and as
many `pointermove`s as `pointerrawupdate`s.

`input-coalescing-parity.patch` queues juggler moves the way real ones are
queued, and `BrowserChild::RecvRealMouseMoveEvent` acks each one with
`mousequeued <id>` when the renderer has it. A move returns at that ack
(`MouseDispatch.sendQueuedMove`). Moves are spaced at least 8 ms apart, the
reports of a 125 Hz mouse, the common rate. A path given as steps
(`page.mouse.move(x, y, steps=n)`, which Playwright sends as n moves) then
reaches the page as a real mouse's motion does. Measured with a 125 Hz XTest
sweep on Xvfb against stock 158.0.1: one
`pointermove` per frame carrying 2 to 4 moves, and a `pointerrawupdate` for
every move.

The coalesced move reaches the page at the refresh tick and is acked as
`mousemove <id>`, with the id of the newest move it carries. Any command of the
page other than another move waits for that ack first (`PageHandler
.beforeDispatch`, called by the protocol session). So whatever a caller does
after `page.mouse.move()` returns sees the move, whether that is an evaluate, a
click or a key. A move with a button held also waits for it before returning,
because the page decides at that tick whether the move starts a drag.

Both waits are bounded by `kAckDeadlineMs`. A page that blocks its main thread
past the deadline only ends the wait; the move stays queued and still reaches
the page. `browser/tests/playwright/patches/driven-move-coalescing.py` checks
the page's counts.

## Drags

On GTK a drag's motion fires `drag` at the source and then `dragover` at the
target (`nsDragSession::DispatchMotionEvents`). The `drag` has `buttons` 0.
The `dragover` GTK sends before a drop is not a motion, so it has no `drag`.
Juggler sends `drag` ahead of each motion's `dragover`.
`drag-source-events.patch` adds the `"drag"` type to `jugglerSendMouseEvent`,
which fires it at the drag session's source. The `pointercancel` that ends the
pointer stream at `dragstart` carries one coalesced event, the move that
started the drag, now that the move reaches the page coalesced.
`browser/tests/playwright/patches/driven-drag-gtk.py` compares the stream
with stock's.

## Wheel notches

A mouse wheel turns in notches, and stock Firefox delivers each one as its own
`wheel` event. On Linux (GTK, X11) stock 158.0.1 gives every notch
`deltaMode` 1, `deltaY` 6, `wheelDeltaY` -120, a `DOMMouseScroll` with
`detail` 3 and a `MozMousePixelScroll` of three lines, and scrolls 120 px
(measured with XTest button 5). `Page.dispatchWheelEvent` sends the same: one
event of three lines per notch, flagged as a native tick
(`wheel-native-ticks.patch`), so Gecko applies the same system scroll speed.

A Playwright caller asks for pixels, so `mouse.wheel(dx, dy)` maps each axis to
notches: 100 px is one notch, rounded to the nearest, at least one on an axis
that moves. The notches of one call are 18 to 60 ms apart, drawn per notch;
no recording of a person's wheel backs that range yet. The page therefore scrolls a
notch's distance (120 px here), not the exact pixels asked for, and
`mouse.wheel(0, 0)` sends nothing. Humanize does not change this.
`browser/tests/playwright/patches/driven-wheel-notches.py` compares the result
with stock's.

## The page's globals

A window defines a WebIDL interface's name on itself the first time anything
needs the interface, so `Object.getOwnPropertyNames(window)` lists the
interfaces in the order they were first used, followed by the unused ones.
A driver's work used to show up in that list. Wrapping the page's nodes for
an isolated world, a locator's reads and an `evaluate` all create interfaces
in the page's window, and creating one defined its name there.

`isolated-world-global-order.patch` creates an interface Juggler needs
without defining its name, and marks it and its prototype in the window's
`ProtoAndIfaceCache`. The page defines it, with its legacy aliases and factory
functions in creation order, when it first uses it, as stock does:

- by name (`WebIDLGlobalNameHash::DefineIfEnabled`);
- by creating an object of it or of an interface that inherits from it
  (`GetPerInterfaceObjectHandle`);
- by getting an object Juggler had already wrapped
  (`MaybeDefineForCachedReflector`).

An Xray of a window first resolves a name on the window itself, which defines
it there. For Juggler that resolve now only creates the interface, and the Xray
resolve that follows hands it over.

Juggler is the caller when the innermost script is one of its
`resource://gre/modules/juggler/` modules, described from the module's own
realm because the page's principal does not see system frames, or runs in a
sandbox one of them created. A callback hides the caller; its incumbent global
decides then, so a listener in one of Juggler's isolated worlds is Juggler's,
and a page's or a browser actor's is not.

`browser/tests/playwright/patches/driven-evaluate-globals.py` lists a page's
globals after driver work and after only the input that work causes, and
compares the two.

## Screenshots

Unless told `caret: "initial"`, Playwright hides the text caret for a
screenshot: from its utility world it sets `caret-color: transparent
!important` in the style attribute of every input, textarea and
contenteditable element, and puts the old value back after the capture. The
page can see all of it. A MutationObserver gets a `style` mutation for each
element, twice per screenshot. `getComputedStyle` reads the transparent caret
while the capture runs. Every element that had no inline style is left with an
empty `style=""` attribute.

Juggler captures with `drawSnapshot`, which never paints the caret, so hiding
it changes no pixel. The launchers therefore default screenshots of pages they
launched to `caret: "initial"`. Page, element and locator screenshots all get
it. Python wraps the client's `Page.screenshot` and `ElementHandle.screenshot`
(`camoufox/screenshots.py`). TypeScript fills the option in where the client
sends the request (`attachScreenshotDefaults` in `utils.ts`). Each checks that
the page belongs to a Camoufox launch, so other browsers in the same process
keep Playwright's behaviour. A caller who passes `caret` gets what they ask
for, and `caret: "hide"` writes the page's style attributes as before. A
client that connects through `launch_server` is not a launcher, so it should
pass `caret: "initial"` itself. The `@playwright/test` `toHaveScreenshot`
assertion passes `caret: "hide"` explicitly, so it also hides the caret.

The guard `screenshot-leaves-page` takes page, element and locator screenshots
with a focused caret. It checks that the page observes no change and is left
with no new attribute, and that each capture is byte-identical to one taken
with `caret: "hide"`.
