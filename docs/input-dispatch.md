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
`MouseDispatch.sendAcked()` measures again before every event it sends, so each
step of a humanized move, dispatched over hundreds of ms, goes out against
where the browser is then; a step in a band of the viewport the window does
not show is skipped, and a destination there is scrolled into view first.
Measured 2026-10-31: in a window too small for the chrome plus the viewport
(a 1366x768 screen draw), Juggler's `.browserStack` scrolled the browser on a
wheel turn, and a move that kept its starting rect landed every later point,
the destination included, 13-84 px off. The stack
is `overflow: hidden` since, so only Juggler's own `scrollRectIntoViewIfNeeded`
scrolls it.

**Bounded waits.** `sendAcked()` waits at most `kAckDeadlineMs` (5s) and then
drops the event with a warning naming the type, coordinate and browser rect. The
deadline is sized above the slowest *legitimate* ack, not near the typical one:
acks are p99 1ms on an idle page, but they are delivered from the content main
thread and inherit any block on it — a 3s synchronous script delayed one by
2849ms. `sendTrajectoryAcked()` abandons the rest of a curve after the first
undelivered point and goes straight to the destination, so the ~90 bounded waits
a curve can hold — the 1.5s default humanize ceiling at 60Hz — cannot add up to
an unbounded slot. `input/Pacer.js` paces each move on its own schedule and
fast-forwards one that runs past 1.5x its time budget. It also refuses
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

## Focus

A driven page stays focused and active, deliberately not stock. Upstream
Playwright's Juggler set `docShell.overrideHasFocus` and `forceActiveState` on
every top-level document so parallel pages behave as if each is in front;
Camoufox keeps that for the product (`content/main.js`). Stock gives a page
behind another window `hasFocus()` false, a window `blur`, and a hidden,
throttled state behind a foreground tab. The difference is page-visible
(`ci/tribal-rules.yml`, `driven-pages-stay-focused`).
Keyboard input therefore does not raise the page first; `Page.bringToFront`
still does that when a caller asks.

## The input gate

Firefox's content process drops user input that reaches a document before its
input gate opens: `dom.input_events.security.minTimeElapsedInMS` (100 ms) after
`readyState` became `"loading"`, then `minNumTicks` refresh ticks
(`PresShell::CanHandleUserInputEvents`). Juggler's mouse and key events are
synthesized for tests, which the gate exempts, so they reached a page earlier
than any person's could; its wheel is not exempt, so a wheel straight after
`goto` lost notches. Every input command now waits for the gate once per
document (`PageHandler._awaitUserInputGate`). Guard: `juggler-input-gate.py`.

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
(`MouseDispatch.sendQueuedMove`). Sends are spaced at least 8 ms apart, the
reports of a 125 Hz mouse, the common rate. The clock starts when the move is
sent, not when its ack returns: the next move cannot start until this one
returns, so counting the ack into the gap stretched a 125 Hz path out to about
one move per frame. A path given as steps
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
(measured with XTest button 5). On Windows, stock 159.0 has the same shape
(measured with `SendInput` at a device pixel ratio of 2.5, 45 runs identical):
`deltaMode` 1, `deltaY` 6, `wheelDeltaY` -120, `detail` 3, one event per notch
with no acceleration. Its pixels differ only because line height does, so three
native lines need no per-OS constant. A physical wheel, other line settings and
a ratio of 1 are not measured there. macOS differs: with a person turning a
notched USB mouse on stock 159.0, a slow notch is `deltaMode` 1, `deltaY` 1,
`wheelDeltaY` -48, `detail` 1 and a `MozMousePixelScroll` of 16, and the OS
accelerates a faster turn to as many as 6 lines an event.

On a Linux or Windows identity, `Page.dispatchWheelEvent` sends one event of three
lines per notch, flagged as a native tick (`wheel-native-ticks.patch`), so Gecko
applies the same system scroll speed. On a macOS identity it sends lines without
that flag and the launcher turns `mousewheel.system_scroll_override.enabled` off,
as stock has it on macOS, which gives the shape above in proportion. Every one of
the 78 recorded macOS bursts starts at one line, so a call starts there too and
grows by 1 to 3 lines an event up to 12.

A Playwright caller asks for pixels, so `mouse.wheel(dx, dy)` maps each axis to
notches: 100 px is one notch, rounded to the nearest, at least one on an axis
that moves. On a macOS identity it maps to lines instead, at 16 px a line. The
events of one call are 18 to 60 ms apart, drawn per event; the
one recording of a person's wheel, on macOS, has bursts 20 to 80 ms apart (10th
to 90th percentile), and nothing backs the range on Linux or Windows. The page therefore scrolls a
notch's distance (120 px here) or a whole number of lines, not the exact pixels asked for, and
`mouse.wheel(0, 0)` sends nothing. Humanize does not change this. Each notch takes the activation slot alone, so a
long wheel does not hold up input in other contexts.
`browser/tests/playwright/patches/driven-wheel-notches.py` compares the result
with stock's.

## Pasted text

Playwright's `fill()` and `keyboard.insert_text()` send `Page.insertText`. A
person enters a whole string by pasting it, so Juggler pastes: the paste
shortcut goes down (Ctrl+V, or Cmd+V when the page's `navigator.platform` is
a Mac), Firefox's own paste runs with the text (`nsIEditor.pasteTransferable`:
a trusted `paste` event whose `clipboardData` holds the text as `text/plain`,
then `beforeinput` and `input` with `insertFromPaste`), and the shortcut comes
up. The shortcut's `keypress`, where Firefox would paste from the system
clipboard, is cancelled in the system group; content never receives a
`keypress` for a shortcut, so that is not observable. The text never goes
through the system clipboard. The modifier leads V by about 60 ms and trails
it by about 40 ms, as Shift does a key, and V is held 116.25 ms (SD 23.88;
Dhakal et al., "Observations on Typing from 136 Million Keystrokes", CHI 2018).
Every delay between a person's input events comes from `input/HumanDelay.js`,
with the figures its caller cites: a normal draw for a key or modifier hold
(`normalDelay(mean, sd, min, max)`) and a right-skewed log-normal for a click
hold, hover dwell or double-click gap (`logNormalDelay(median, sigma, min, max)`),
as human timing is.

A page that cancels the paste, or the shortcut's `keydown`, and leaves the field
as it was gets the text typed instead, as a person types what they cannot paste:
key by key on a US keyboard, 238.66 ms press to press (SD 111.60, the same study).
A character with no US key arrives as an input method commits it. Typing stops
with an error if the focus leaves the field, and a read-only field takes nothing,
without error. A page that writes the pasted text in later than the shortcut's
release (about 160 ms) has it typed as well. A page that
handled the paste itself keeps what it wrote, and `fill()` fails only if the keys
change nothing either. Nothing focused that takes text gets the shortcut and no
paste. Playwright documents `insert_text()` as sending no key events; here it
sends the shortcut's.

A person clicks a field before pasting into it, while Playwright's `fill()`
focuses it from script: the page would get `focus` with no pointer or mouse
event before it. The Python launcher clicks a text field that does not have
focus before the fill (`camoufox/driver_defaults.py`), and so does the TypeScript
launcher (`driver_defaults.ts`). The click is Playwright's own, so the mouse moves
there and presses through the OS-path dispatch. A field that has focus is pasted
into as it is. Fields `fill()` sets without pasting (date, color, range and the
like) are not clicked, and neither is a field another element covers, which a
person could not click either: `fill()` works on it as Playwright's does.
`fill()` still selects the field's text with `select()` first.
`browser/tests/playwright/patches/driven-fill-paste.py` checks the events.

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
(`camoufox/driver_defaults.py`). TypeScript fills the option in where the client
sends the request (`attachDriverDefaults` in `driver_defaults.ts`). Each checks that
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

## The page's globals

A window defines a WebIDL interface's name on itself the first time anything
needs the interface, so `Object.getOwnPropertyNames(window)` lists the
interfaces in the order they were first used, followed by the unused ones.
A driver's work used to show up in that list. Wrapping the page's nodes for
an isolated world, a locator's reads and an `evaluate` all create interfaces
in the page's window, and creating one defined its name there:
HTMLDivElement, CSSStyleDeclaration, DOMRect, MutationObserver, AbortSignal
and some 30 others moved up the list of a page that had never used them.

`isolated-world-global-order.patch` creates an interface Juggler needs
without defining its name, and marks it and its prototype in the window's
`ProtoAndIfaceCache`. The window keeps listing it as unused. The page defines
it, with its legacy aliases and factory functions in creation order, when it
first uses it, as stock does:

- by name (`WebIDLGlobalNameHash::DefineIfEnabled`);
- by creating an object of it or of an interface that inherits from it
  (`GetPerInterfaceObjectHandle`);
- by getting an object Juggler had already wrapped, such as an input a
  browser actor reads on focus (`MaybeDefineForCachedReflector`). The check
  costs one array read per cached reflector handed out
  (`DoGetOrCreateDOMReflector`): a count, per interface prototype, of the
  windows holding it created for Juggler and not yet defined, so a
  reflector of any other interface costs what it does in stock. An object the page creates is
  checked against its own interface's mark the same way.

An Xray of a window first resolves a name on the window itself (the
generated `ResolveOwnPropertyViaResolve`), which defines it there. For
Juggler that resolve now only creates the interface, and the Xray resolve
that follows hands it over: Playwright's utility script reads `AbortSignal`
this way.

Juggler is the caller when the innermost script is one of its
`resource://gre/modules/juggler/` modules, described from the module's own
realm because the page's principal does not see system frames, or runs in a
sandbox one of them created. A callback hides the caller; its incumbent global
decides then, so a listener in one of Juggler's isolated worlds (Playwright's
hit target check) is Juggler's, and a page's or a browser actor's is not. The
entry global is no guide: Juggler's actor messages enter the page's window.

`browser/tests/playwright/patches/driven-evaluate-globals.py` lists a page's
globals after driver work and after only the input that work causes (a click
on a field and a key, which Firefox's own actors wrap in the page's window as
they do for a person's input), and compares the two.
