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

/** Delay between humanized trajectory points, preserving the original cadence. */
export const kTrajectoryStepMs = 10;

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
   */
  constructor(win, boundingBox, {button = 0, clickCount = 0, modifiers = 0, buttons = 0} = {}) {
    this._win = win;
    this._box = boundingBox;
    this._args = {button, clickCount, modifiers, buttons};

    // The first whole pixel inside the browser element on each axis.
    //
    // The element's origin is not pixel-aligned: the chrome above the content is
    // a fractional number of CSS pixels tall, and how many depends on the spoofed
    // OS (measured: windows 51.4, macos 53.1, linux 56.5). A relative coordinate
    // of 0 therefore dispatches at absolute y == boundingBox.top exactly -- the
    // content area's first, only partly covered row. The widget rounds that to a
    // whole device row before hit-testing it, and wherever round(top) < top the
    // rounded row still belongs to chrome, so the event fires as an exit event
    // rather than eMouseMove and no ack is ever produced (#751, #752).
    //
    // Snapping onto ceil() keeps the point inside content pixel 0 while landing
    // clear of the boundary. It is a sub-pixel shift and only ever affects the
    // first row/column; boundingBox.left is normally a whole 0 and unaffected.
    this._originX = Math.ceil(boundingBox.left);
    this._originY = Math.ceil(boundingBox.top);

    // The far edge has the same problem, and the bounds check below cannot see
    // it either. The element's height is fractional too -- measured, it is
    // consistently 0.5 CSS px less than the innerHeight the page reports, so
    // the page's last row is only half covered. A point in it dispatches at an
    // absolute coordinate that rounds onto the row *past* the content, and is
    // dropped exactly like the top-edge case. Deterministic: with the box at
    // 1920x977.5 +0+56.5, relative y == 977 (innerHeight - 1, well inside the
    // viewport as far as the page is concerned) dispatches at 1033.5, rounds to
    // 1034, and the content ends at 1034.
    //
    // So clamp to the last whole pixel fully inside the element as well. Found
    // by tests/patches/mouse-boundary-sweep.py, not by a report -- it predates
    // this module and deadlocks a stock build.
    this._limitX = Math.ceil(boundingBox.left + boundingBox.width) - 1;
    this._limitY = Math.ceil(boundingBox.top + boundingBox.height) - 1;
  }

  static forBrowser(win, linkedBrowser, eventArgs) {
    return new MouseDispatch(win, linkedBrowser.getBoundingClientRect(), eventArgs);
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
      this._win.MouseEvent.MOZ_SOURCE_MOUSE /* inputSource */,
      true /* isDOMEventSynthesized */,
      false /* isWidgetEventSynthesized */,
      this._args.buttons,
      this._win.windowUtils.DEFAULT_MOUSE_POINTER_ID /* pointerIdentifier */,
      false /* disablePointerEvent */
    );
  }

  /**
   * Dispatch one event and wait for the renderer to ack it, under a deadline.
   *
   * Returns the ack event object, or null if none arrived in time -- in which
   * case the event is dropped and a warning is logged. Never rejects and never
   * waits forever: input dispatch is serialized on activateAndRun()'s
   * process-global chain, so an unbounded wait here wedges every later input
   * event in the process, in every tab, for the life of the browser.
   */
  async sendAcked(watcher, eventType, x, y, deadlineMs = kAckDeadlineMs) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    // This dispatches to the renderer synchronously.
    const jugglerEventId = this._sendAbsolute(eventType, absX, absY);
    const ack = await watcher.ensureEventWithin(
      eventType, deadlineMs, eventObject => eventObject.jugglerEventId === jugglerEventId);
    if (!ack)
      warnUndelivered(eventType, x, y, this._box, deadlineMs);
    return ack;
  }

  /**
   * Dispatch the intermediate points of a humanized trajectory.
   *
   * Points outside the viewport are skipped. Bounding each ack individually is
   * not enough to bound the work: a curve is ~110 points dispatched inside a
   * SINGLE activation-chain slot, so a curve riding a coordinate that cannot be
   * delivered would spend 110 x the deadline there. Rather than a wall-clock
   * budget -- which would false-fire on exactly the slow pages the deadline
   * exists to tolerate -- the first undelivered point abandons the rest of the
   * curve. Intermediate points are humanization garnish: if one did not reach
   * the renderer the rest of that curve almost certainly will not either, and
   * dropping them costs realism, not correctness. The caller still dispatches
   * the real destination afterwards.
   *
   * @returns {boolean} true if the whole curve was delivered.
   */
  async sendTrajectoryAcked(watcher, eventType, points, stepDelayMs = kTrajectoryStepMs) {
    for (const [x, y] of points) {
      if (!this.isInViewport(x, y))
        continue;
      if (!await this.sendAcked(watcher, eventType, x, y))
        return false;
      await new Promise(resolve => setTimeout(resolve, stepDelayMs));
    }
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

  /** Wheel events take the same conversion; they are not acked. */
  sendWheel(x, y, {deltaX, deltaY, deltaZ, deltaMode, lineOrPageDeltaX, lineOrPageDeltaY}) {
    const {x: absX, y: absY} = this.toAbsolute(x, y);
    this._win.windowUtils.sendWheelEvent(
      absX,
      absY,
      deltaX,
      deltaY,
      deltaZ,
      deltaMode,
      this._args.modifiers,
      lineOrPageDeltaX,
      lineOrPageDeltaY,
      0 /* options */);
  }
}
