/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * The `notches` scroll engine: scroll the way a physical wheel does.
 *
 * Each notch is its own event of 3 LINES carrying one native tick, so the page
 * sees deltaMode 1, DOMMouseScroll.detail 3 and wheelDelta -120 per notch, and
 * a longer scroll arrives as several such events a few tens of ms apart.
 * Playwright's pixel delta gives detail = 100 and no line delta; lines without
 * ticks give wheelDelta -396 for one notch and one big event for several
 * (measured against XTEST input). 100 px == one notch.
 *
 * Quantising into notches changes the number the page sees, so this engine is
 * opt-in: with scroll `raw`, mouse.wheel(0, 100) delivers deltaY 100 in
 * deltaMode 0, the delta the caller asked for and what upstream's suite asserts.
 */

const kPxPerNotch = 100;
const kLinesPerNotch = 3;

function toNotches(delta) {
  return delta === 0 ? 0 : Math.sign(delta) * Math.max(1, Math.round(Math.abs(delta) / kPxPerNotch));
}

export const notches = {
  /**
   * @param ctx the seam's plan context; only `ctx.rng` is used.
   * @param at {x, y} where the wheel turns, browser-relative.
   * @param delta {deltaX, deltaY, deltaZ} as Page.dispatchWheelEvent got them.
   */
  planWheel(ctx, at, {deltaX, deltaY, deltaZ}) {
    const notchesX = toNotches(deltaX);
    const notchesY = toNotches(deltaY);
    const count = Math.max(1, Math.abs(notchesX), Math.abs(notchesY));
    const steps = [];
    let t = 0;
    for (let i = 0; i < count; i++) {
      if (i)
        t += 18 + ctx.rng() * 42;
      const lines = n => (i < Math.abs(n) ? Math.sign(n) * kLinesPerNotch : 0);
      steps.push({
        kind: 'wheel', t, x: at.x, y: at.y,
        dx: lines(notchesX), dy: lines(notchesY), dz: i ? 0 : deltaZ,
        mode: 1 /* WheelEvent.DOM_DELTA_LINE */,
        ticks: {x: lines(notchesX), y: lines(notchesY)},
        // Every notch carries part of the requested distance.
        essential: true,
      });
    }
    return {steps, endState: {}};
  },
};
