/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * The one place in the parent process that dispatches synthesized mouse input.
 *
 * It exists because the alternative did not work. Between 2026-04 and 2026-09,
 * four separate deadlocks shipped -- exact-edge coordinates (#225), humanized
 * trajectory points that bypassed the endpoint's guard (#677/#225), a
 * zero-displacement move, and the top-edge row (#751/#752) -- each fixed by
 * adding one more coordinate guard at one more call site. The guards were
 * correct; the arithmetic behind them was copied per call site, so every new
 * dispatch site was a fresh chance to get it wrong, and every mistake cost the
 * whole browser process.
 *
 * THE INVARIANT
 *   A synthesized input event whose ack we await must reach the content
 *   renderer -- and when it does not, we must stop waiting.
 *
 * Nothing else in juggler may call jugglerSendMouseEvent / sendWheelEvent or do
 * browser-relative coordinate arithmetic; scripts/check-input-dispatch.py fails
 * the build if it does. See docs/input-dispatch.md.
 */

const {setTimeout} = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');

/**
 * How long to wait for a juggler-mouse-event-hit-renderer ack before giving up.
 *
 * Measured on v152.0.4-beta.30, headless Linux, over 1000+ dispatches:
 *
 *   content main thread        p50     p99     max
 *   idle                       0ms     1ms     12ms
 *   busy (8ms burned/event)    8ms     9ms     12ms
 *   blocked (3s sync script)   0ms     1ms     2849ms
 *
 * Typical latency is three orders of magnitude below this. The deadline is not
 * sized by the typical case though: the ack is delivered FROM the content main
 * thread, so it inherits any block on it, and block length is page-controlled
 * and unbounded. Pages that block for seconds are the normal case on the
 * targets Camoufox exists to handle. Sizing this near the p99 would silently
 * drop real input on merely-slow pages -- a correctness bug wearing the exact
 * costume of the deadlock it replaces. Waiting too long costs a few seconds
 * once and then recovers; waiting too little costs input loss that nobody can
 * diagnose. So: well above the slowest legitimate ack, not near the typical one.
 */
export const kAckDeadlineMs = 5000;

function warnUndelivered(eventType, x, y, box, deadlineMs) {
  dump(
    `[juggler] WARN ${eventType} at (${x}, ${y}) was not delivered to the ` +
    `renderer after ${deadlineMs}ms; dropping it (browser rect ` +
    `${box.width}x${box.height} at +${box.left}+${box.top})\n`
  );
}

export class MouseDispatch {
  /**
   * @param {Window} win chrome window owning the browser element.
   * @param {DOMRect} boundingBox the browser element's rect, already measured.
   * @param {object} eventArgs button / clickCount / modifiers / buttons.
   * @param {Element} [browser] measured again before each dispatch when given.
   */
  constructor(win, boundingBox, {button = 0, clickCount = 0, modifiers = 0, buttons = 0} = {}, browser = null) {
    this._win = win;
    this._args = {button, clickCount, modifiers, buttons};
    this._browser = browser;
    this._measured(boundingBox);
  }

  _measured(boundingBox) {
    this._box = boundingBox;

    // Snap onto whole pixels fully inside the browser element. Its origin and
    // size can be fractional, and a rounded point on either boundary belongs
    // to chrome rather than content, so no renderer ack arrives (#751, #752).
    this._originX = Math.ceil(boundingBox.left);
    this._originY = Math.ceil(boundingBox.top);
    this._limitX = Math.ceil(boundingBox.left + boundingBox.width) - 1;
    this._limitY = Math.ceil(boundingBox.top + boundingBox.height) - 1;
  }

  static forBrowser(win, linkedBrowser, eventArgs) {
    return new MouseDispatch(win, linkedBrowser.getBoundingClientRect(), eventArgs, linkedBrowser);
  }

  _remeasure() {
    if (this._browser)
      this._measured(this._browser.getBoundingClientRect());
  }

  get boundingBox() {
    return this._box;
  }

  /**
   * Is this relative point inside the content viewport at all?
   *
   * The far edges are exclusive: a point at exactly x == width or y == height
   * lies on the opposite boundary row and fires as an exit event, so it must be
   * treated as out-of-viewport rather than dispatched (#225). The near edges are
   * inclusive -- 0 is a legitimate coordinate a caller may ask for, and the
   * constructor's snap is what makes it safe to dispatch.
   */
  isInViewport(x, y) {
    return x >= 0 && y >= 0 && x < this._box.width && y < this._box.height;
  }

  /** Relative point -> absolute, snapped clear of both of the element's edges. */
  toAbsolute(x, y) {
    return {
      x: Math.min(Math.max(x + this._box.left, this._originX), this._limitX),
      y: Math.min(Math.max(y + this._box.top, this._originY), this._limitY),
    };
  }

  _sendAbsolute(eventType, absX, absY) {
    return this._win.windowUtils.jugglerSendMouseEvent(
      eventType,
      absX,
      absY,
      this._args.button,
      this._args.clickCount,
      this._args.modifiers,
      false /* aIgnoreRootScrollFrame */,
      0.0 /* pressure */,
      // MOZ_SOURCE_MOUSE: a real mouse reports PointerEvent.pointerType "mouse";
      // MOZ_SOURCE_UNKNOWN (0) surfaces as an empty pointerType, which no OS
      // input path ever produces (daijro/camoufox#776, microsoft/playwright#38376).
      this._win.MouseEvent.MOZ_SOURCE_MOUSE /* inputSource */,
      true /* isDOMEventSynthesized */,
      false /* isWidgetEventSynthesized */,
      this._args.buttons,
      this._win.windowUtils.DEFAULT_MOUSE_POINTER_ID /* pointerIdentifier */,
      false /* disablePointerEvent */
    );
  }

  /**
   * The open chrome popup over an absolute point, if there is one.
   *
   * The parent hands a mouse event at a point inside a visible popup (the date
   * picker, a permission doorhanger) to that popup, not to the browser under
   * it (PresShell::EventHandler::ComputeRootFrameToHandleEventWithPopup), as
   * an OS click there lands on the popup. The renderer never sees it, so there
   * is no ack to wait for. Waiting cost 5s per event (kAckDeadlineMs): a
   * click under the picker showPicker() opened took 15s and timed out
   * Playwright, where stock's click went to the picker at once (2026-11-03,
   * tests/playwright/patches/popup-covered-click.py). Mirrors
   * nsXULPopupManager::GetVisiblePopups: open, and not transparent to the mouse.
   */
  _popupAt(absX, absY) {
    const doc = this._win.document;
    let point = null;
    for (const popup of doc.querySelectorAll('panel, menupopup, tooltip')) {
      if (popup.state !== 'open' || this._win.getComputedStyle(popup).pointerEvents === 'none')
        continue;
      point ??= this._win.windowUtils.toScreenRectInCSSUnits(absX, absY, 0, 0);
      const r = popup.getOuterScreenRect();
      if (point.x >= r.left && point.x < r.right && point.y >= r.top && point.y < r.bottom)
        return popup;
    }
    return null;
  }

  /**
   * Dispatch one event and wait for the renderer to ack it, under a deadline.
   *
   * Returns the ack event object, or null if none arrived in time -- in which
   * case the event is dropped and a warning is logged -- or {popup} at once
   * when an open popup over the point took the event (_popupAt). Never rejects and never
   * waits forever: input dispatch is serialized on activateAndRun()'s
   * process-global chain, so an unbounded wait here wedges every later input
   * event in the process, in every tab, for the life of the browser.
   */
  async sendAcked(watcher, eventType, x, y, deadlineMs = kAckDeadlineMs) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    const popup = this._popupAt(absX, absY);
    // This dispatches to the renderer synchronously.
    const jugglerEventId = this._sendAbsolute(eventType, absX, absY);
    if (popup)
      return {jugglerEventId, popup};
    // A move reaches the page at the next refresh tick; the renderer acks it
    // on arrival as "mousequeued" (BrowserChild::RecvRealMouseMoveEvent).
    const arrival = eventType === 'mousemove' ? 'mousequeued' : eventType;
    const ack = await watcher.ensureEventWithin(
      arrival, deadlineMs, eventObject => eventObject.jugglerEventId === jugglerEventId);
    if (!ack)
      warnUndelivered(eventType, x, y, this._box, deadlineMs);
    return ack;
  }

  /**
   * Dispatch a move and wait until the renderer has queued it. The page gets
   * it at the next refresh tick, coalesced with the moves queued since the
   * last one; the returned handle's delivered() waits for that, under the
   * same deadline (deliveryWatcher must listen for 'mousemove' from before
   * the dispatch). Returns null when the move was not queued in time.
   */
  async sendQueuedMove(watcher, deliveryWatcher, x, y) {
    const queued = await this.sendAcked(watcher, 'mousemove', x, y);
    // A move a popup took never reaches the page either.
    if (!queued || queued.popup) {
      deliveryWatcher.dispose();
      return null;
    }
    return {
      // A newer move disposes this watcher: that move is then the one to wait for.
      delivered: async () => {
        const ack = await deliveryWatcher.ensureEventWithin(
          'mousemove', kAckDeadlineMs, eventObject => eventObject.jugglerEventId === queued.jugglerEventId)
          .catch(() => true);
        if (!ack)
          dump(`[juggler] WARN a queued mousemove at (${x}, ${y}) had not reached the page after ${kAckDeadlineMs}ms; going on\n`);
        return ack;
      },
      dispose: () => deliveryWatcher.dispose(),
    };
  }

  /**
   * Dispatch the intermediate points of a humanized trajectory.
   *
   * Each step carries its own pause because the trajectory generator
   * (input/CursorTrajectory.js) replays timing recorded from a real hand: the
   * gaps are uneven, and evening them out would throw away the half of the
   * realism that is not the shape of the path. The pause is taken BEFORE the
   * point it belongs to, and it is taken even for a point that is then skipped,
   * so dropping a point shifts nothing that follows it in time.
   *
   * The pauses are a schedule counted from the start of the curve, not gaps
   * taken after each ack: every point waits until its own due time. Waiting a
   * full gap after the ack added each ack's latency to the curve, so a move ran
   * as long as its plan plus one round trip per point: on a page busy 19ms in
   * every 20, moves planned at 0.5s took 0.54-0.71s (tests/playwright/patches/
   * humanize-pacing.py). A late point is dispatched as soon as it can be; the
   * ones after it are still due on the original clock.
   *
   * Points outside the viewport are skipped, and a curve leaves the viewport
   * more often than it sounds: measured over 400 random moves, 69% of Cursory
   * paths stray outside the box spanned by their own endpoints, by up to 184px.
   *
   * Bounding each ack individually is not enough to bound the work: a curve is
   * dispatched inside a SINGLE activation-chain slot, and holds up to ~90
   * points at the 1.5s default ceiling (the generator holds the sample rate at
   * 60Hz however the duration is scaled; measured worst case over 800 moves was
   * 83). A curve riding a coordinate that cannot be delivered would spend 90 x
   * the deadline there. Rather than a wall-clock
   * budget -- which would false-fire on exactly the slow pages the deadline
   * exists to tolerate -- the first undelivered point abandons the rest of the
   * curve. Intermediate points are humanization garnish: if one did not reach
   * the renderer the rest of that curve almost certainly will not either, and
   * dropping them costs realism, not correctness. The caller still dispatches
   * the real destination afterwards.
   *
   * @param {Array<[number, number, number]>} steps [x, y, msToPauseBeforeIt].
   * @param {number} trailingDelayMs pause before the caller's own dispatch of
   *   the destination, so the movement ends on the generator's clock and not
   *   the moment its last intermediate point landed.
   * @returns {boolean} true if the whole curve was delivered.
   */
  async sendTrajectoryAcked(watcher, eventType, steps, trailingDelayMs = 0) {
    // A point on the pixel the cursor is already on generates no eMouseMove, so
    // it is never acked and the wait below would burn the whole deadline. The
    // generator already drops those, but it cannot see which points this method
    // skipped for being off-screen, and skipping one can leave the next landing
    // back where the last dispatch left the cursor. Tracking what was actually
    // dispatched is the only place that check is reliable.
    let lastX = NaN;
    let lastY = NaN;
    const startMs = ChromeUtils.now();
    let dueMs = 0;
    const untilDue = () => {
      const waitMs = startMs + dueMs - ChromeUtils.now();
      return waitMs > 0 ? new Promise(resolve => setTimeout(resolve, waitMs)) : null;
    };
    for (const [x, y, delayMs] of steps) {
      dueMs += delayMs;
      await untilDue();
      this._remeasure();
      if (!this.isInViewport(x, y))
        continue;
      if (Math.round(x) === lastX && Math.round(y) === lastY)
        continue;
      if (!await this.sendAcked(watcher, eventType, x, y))
        return false;
      lastX = Math.round(x);
      lastY = Math.round(y);
    }
    dueMs += trailingDelayMs;
    await untilDue();
    return true;
  }

  /**
   * Park the cursor off web content so hover effects clear.
   *
   * Deliberately dispatched at the chrome window's own origin rather than a
   * content coordinate, and deliberately unacked: it never enters the renderer,
   * so there is no ack to wait for.
   */
  parkOffContent() {
    this._sendAbsolute('mousemove', 0, 0);
  }

  /**
   * The pointer leaves the window, or comes back to it at a relative point, as
   * when a GTK drag session takes the pointer and gives it back. A widget exit
   * and enter, sent to the chrome window so the parent's hover state leaves as
   * well as the page's. Unacked: neither is a mouse event the renderer acks.
   */
  leaveWindow(x, y) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    this._sendAbsolute('mousecancel', absX, absY);
  }

  enterWindow(x, y) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    this._sendAbsolute('mouseover', absX, absY);
  }

  /**
   * One wheel notch of `linesX`/`linesY` lines, as a mouse wheel's native tick.
   * Same conversion as mouse events; not acked.
   */
  sendWheel(x, y, linesX, linesY) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    const utils = this._win.windowUtils;
    utils.sendWheelEvent(
      absX,
      absY,
      linesX,
      linesY,
      0,
      1 /* WheelEvent.DOM_DELTA_LINE */,
      this._args.modifiers,
      linesX,
      linesY,
      utils.WHEEL_EVENT_NATIVE_NOTCHES);
  }
}
