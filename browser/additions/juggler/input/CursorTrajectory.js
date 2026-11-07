/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * The cursor path `humanize=True` moves along.
 *
 * Camoufox used to generate this in C++ (additions/camoucfg/MouseTrajectories.hpp):
 * a cubic Bezier through two random knots, distorted, then walked with an
 * ease-out and emitted at a flat 10ms cadence. It was replaced by Cursory
 * (cursory/, vendored) because the two differ in what they are imitating. A
 * Bezier is an equation, and an equation sampled at a fixed rate has velocity
 * and jerk profiles that separate cleanly from a hand's; the old path's speed
 * also came entirely from an easing function, so every movement Camoufox ever
 * made accelerated and decelerated the same way. Cursory replays one of 2356
 * movements recorded from real people, morphed onto the requested endpoints,
 * and keeps that recording's own timing -- pauses, overshoots and all.
 *
 * This module is the whole boundary between Camoufox and Cursory: it owns the
 * cadence and the pixel grid. Wheel notches are planned here too.
 */

const kCursoryUrl = 'resource://gre/modules/juggler/input/cursory/cursory.js';

/**
 * Samples per second.
 *
 * A USB mouse reports at 125Hz, but Gecko coalesces moves to the refresh rate
 * before a page sees them, so 60 is what a page observes from a real cursor on
 * a 60Hz display -- and it is the rate the recordings themselves carry (median
 * gap across all 110664 of their samples: 16ms). Asking for more would not add
 * information, only more synthesized events per move, each of which costs a
 * round trip to the renderer and an ack.
 */
const kFrequencyHz = 60;

/**
 * Default ceiling on how long one movement may take, in seconds.
 *
 * Matches what Camoufox has always documented ("the cursor typically takes up
 * to 1.5 seconds to move across the window") and what the old generator's
 * default worked out to: 150 points at 10ms each. Cursory's own durations come
 * from the recordings and normally land well inside this, so the cap is a
 * backstop against a slow recording, not the thing setting the pace.
 */
const kDefaultMaxTimeSeconds = 1.5;

// Loaded on first use, not at import: the recording database is ~2MB of JSON,
// and a profile that never sets humanize=True should never pay for it.
//
// Measured: ~33ms to read, parse and index, once per process. Generating one
// path afterwards is ~0.5ms (p95 under 1ms, and flat in distance), against a
// movement that then takes several hundred milliseconds to play out -- so the
// generator is nowhere near the cost of the move it describes.
let cursoryModule = null;

function loadCursory() {
  if (!cursoryModule)
    cursoryModule = ChromeUtils.importESModule(kCursoryUrl);
  return cursoryModule;
}

/** The configured [min, max] duration of one movement, in milliseconds. */
function durationBoundsMs({maxTime = kDefaultMaxTimeSeconds, minTime = 0}) {
  const maxMs = Math.max(0, maxTime * 1000);
  // A min above the max would make the clamp below non-monotonic; the max wins,
  // as it did in C++ (std::min of the two point counts).
  return {minMs: Math.min(Math.max(0, minTime * 1000), maxMs), maxMs};
}

/**
 * Past this multiple of its budget, a move whose acks are stalling
 * fast-forwards to its destination. It holds the process-wide activation slot
 * while it plays (kActivationSlotBudgetMs, 30s).
 */
const kDeadlineFactor = 1.5;

const kPxPerNotch = 100;
const kLinesPerNotch = 3;
const kPxPerMacLine = 16;
const kMaxMacLines = 12;

function toNotches(delta) {
  const count = delta === 0 ? 0 : Math.max(1, Math.round(Math.abs(delta) / kPxPerNotch));
  return new Array(count).fill(Math.sign(delta) * kLinesPerNotch);
}

// macOS accelerates a turn: every recorded burst starts at one line and grows
// (docs/input-dispatch.md).
function toMacLines(delta, rng) {
  let left = delta === 0 ? 0 : Math.max(1, Math.round(Math.abs(delta) / kPxPerMacLine));
  const events = [];
  for (let size = 1; left > 0; size = Math.min(kMaxMacLines, size + 1 + Math.floor(rng() * 3))) {
    const lines = Math.min(size, left);
    events.push(Math.sign(delta) * lines);
    left -= lines;
  }
  return events;
}

/**
 * Plans a humanized mousemove from `ctx.cursor` to `to`.
 *
 * Coordinates are browser-relative, exactly as MouseDispatch wants them. The
 * plan's steps are `{kind: 'move', x, y, t}` with `t` in ms from the start of
 * the move, and the last step is always the destination itself: the move has
 * to finish exactly on the requested coordinate whatever happens to the curve,
 * and it is the one point that must not be dropped for being off-screen or
 * off-grid. Every other step is garnish that dispatch may drop.
 *
 * `ctx.options` carries `humanize:maxTime` / `humanize:minTime` (seconds), and
 * `ctx.rng` is the only randomness used.
 */
export const cursory = {
  budgetMs(options) {
    return durationBoundsMs(options).maxMs;
  },

  planMove(ctx, to) {
    const destination = {kind: 'move', x: to.x, y: to.y};
    const {x: fromX, y: fromY} = ctx.cursor;
    // parkOffContent() forgets the cursor position (it sets NaN) because the
    // pointer really did move somewhere untracked. With no start point there is
    // no path to draw, so this move goes straight to its destination.
    if (!Number.isFinite(fromX) || !Number.isFinite(fromY))
      return {steps: [{...destination, t: 0}], endState: {cursor: to}};

    const {minMs, maxMs} = durationBoundsMs(ctx.options);
    const {generateTrajectory} = loadCursory();

    // Cursory takes a 48-bit seed, reused below.
    const seed = Math.floor(ctx.rng() * 2 ** 32) * 2 ** 16 + Math.floor(ctx.rng() * 2 ** 16);
    let {points, timings} = generateTrajectory(
        [fromX, fromY], [to.x, to.y], {frequency: kFrequencyHz, seed});

    // Scale the whole path's timing into the configured bounds rather than
    // truncating it. Truncating would drop the end of every long movement, which
    // is the part that decelerates onto the target -- the most recognizably human
    // part of it.
    const recordedMs = timings[timings.length - 1];
    const scale = recordedMs > 0 ? Math.min(Math.max(recordedMs, minMs), maxMs) / recordedMs : 0;

    // Rescaling the clock without rescaling the sample count would change the
    // rate the events come out at, and the rate is itself a fingerprint. Measured
    // over 1500 moves: 1.8% run past the 1.5s default cap, and the worst was a 5s
    // recording -- 301 points, which compressed into 1.5s is a 200Hz burst, above
    // what any mouse reports and far above what any display coalesces to. A
    // minTime floor has the same problem pointing the other way, stretching a
    // move until it ticks at 14Hz.
    //
    // So ask for the sample count that lands at kFrequencyHz once scaled. The
    // seed is reused deliberately: the recording is chosen before `frequency` is
    // consulted, so the same seed re-picks the same recording with the same
    // natural duration, and `scale` stays exact. Only the resampling differs.
    if (scale > 0 && scale !== 1) {
      ({points, timings} = generateTrajectory(
          [fromX, fromY], [to.x, to.y],
          {frequency: Math.max(1, kFrequencyHz * scale), seed}));
    }

    // A real mouse reports whole pixels, and the widget rounds to a device pixel
    // before hit-testing anyway, so round here and drop points that land on the
    // pixel the cursor is already on. Those are not merely redundant: a
    // zero-displacement move generates no eMouseMove, so it is never acked, and
    // waiting for that ack is one of the deadlocks docs/input-dispatch.md exists
    // to prevent. Their elapsed time is kept -- a hand that hovers a pixel for
    // 30ms took 30ms -- and folded into the next point that does move.
    //
    // This is also why the event rate is only ever *at most* kFrequencyHz: a
    // short move has fewer whole pixels along it than samples, so it reports
    // fewer events, exactly as a real mouse crossing the same distance would.
    // Measured with a 3s floor: 41Hz over 72px, 56Hz over 400px, 60Hz over
    // 2100px.
    const steps = [];
    let previousX = Math.round(fromX);
    let previousY = Math.round(fromY);
    const destinationX = Math.round(to.x);
    const destinationY = Math.round(to.y);
    let t = 0;

    // The first point is where the cursor already is, and the last is the
    // destination, appended below; both ends are excluded.
    for (let i = 1; i < points.length - 1; i++) {
      const x = Math.round(points[i][0]);
      const y = Math.round(points[i][1]);
      if (x === previousX && y === previousY)
        continue;
      // Landing on the destination early would leave the final step with
      // nothing to move, and the same unacked wait.
      if (x === destinationX && y === destinationY)
        continue;
      t = Math.max(t, Math.round(timings[i] * scale));
      steps.push({kind: 'move', x, y, t});
      previousX = x;
      previousY = y;
    }

    steps.push({...destination, t: Math.max(t, Math.round(recordedMs * scale))});
    return {steps, endState: {cursor: to}};
  },

  planWheel(ctx, at, {deltaX, deltaY, deltaZ}) {
    const eventsFor = delta => (ctx.macOS ? toMacLines(delta, ctx.rng) : toNotches(delta));
    const xs = eventsFor(deltaX);
    const ys = eventsFor(deltaY);
    const count = Math.max(1, xs.length, ys.length);
    const steps = [];
    let t = 0;
    for (let i = 0; i < count; i++) {
      if (i)
        t += 18 + ctx.rng() * 42;
      const dx = xs[i] ?? 0;
      const dy = ys[i] ?? 0;
      steps.push({
        kind: 'wheel', t, x: at.x, y: at.y,
        dx, dy, dz: i ? 0 : deltaZ,
        mode: 1,
        ticks: {x: dx, y: dy},
        essential: true,
      });
    }
    return {steps, endState: {}};
  },
};

/** The plan for a `humanize=True` move, and when pacing it must give up. */
export function humanizedMove(cursor, to) {
  const options = {
    maxTime: ChromeUtils.camouGetDouble('humanize:maxTime', kDefaultMaxTimeSeconds),
    minTime: ChromeUtils.camouGetDouble('humanize:minTime', 0),
  };
  return {
    plan: cursory.planMove({cursor, options, rng: Math.random}, to),
    deadlineMs: cursory.budgetMs(options) * kDeadlineFactor,
  };
}
