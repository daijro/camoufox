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
 * config, the cadence and the pixel grid, and hands MouseDispatch a plain list
 * of steps.
 */

const kCursoryUrl = 'chrome://juggler/content/input/cursory/cursory.js';

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
let cursory = null;

function loadCursory() {
  if (!cursory)
    cursory = ChromeUtils.importESModule(kCursoryUrl);
  return cursory;
}

/** The configured [min, max] duration of one movement, in milliseconds. */
function durationBoundsMs() {
  const maxSeconds = ChromeUtils.camouGetDouble('humanize:maxTime', kDefaultMaxTimeSeconds);
  const minSeconds = ChromeUtils.camouGetDouble('humanize:minTime', 0);
  const maxMs = Math.max(0, maxSeconds * 1000);
  // A min above the max would make the clamp below non-monotonic; the max wins,
  // as it did in C++ (std::min of the two point counts).
  return {minMs: Math.min(Math.max(0, minSeconds * 1000), maxMs), maxMs};
}

/**
 * The intermediate points of a humanized move from (fromX, fromY) to (toX, toY).
 *
 * All coordinates are browser-relative, exactly as MouseDispatch wants them.
 *
 * Returns `{steps, trailingDelayMs}`, where each step is `[x, y, delayMs]` --
 * the pause to take *before* dispatching that point -- and `trailingDelayMs` is
 * the pause before the caller's own dispatch of the real destination. The
 * destination is deliberately not a step: the caller has to finish exactly on
 * the requested coordinate whatever happens to the curve, and it is the one
 * point that must not be dropped for being off-screen or off-grid.
 */
export function humanizedSteps(fromX, fromY, toX, toY) {
  // parkOffContent() forgets the cursor position (it sets NaN) because the
  // pointer really did move somewhere untracked. With no start point there is
  // no path to draw, so this move goes straight to its destination.
  if (!Number.isFinite(fromX) || !Number.isFinite(fromY))
    return {steps: [], trailingDelayMs: 0};

  const {minMs, maxMs} = durationBoundsMs();
  const cursory = loadCursory();

  // Seeded explicitly so the same path can be asked for twice -- see below.
  const seed = Number(crypto.getRandomValues(new BigUint64Array(1))[0] >> 16n);
  let {points, timings} = cursory.generateTrajectory(
      [fromX, fromY], [toX, toY], {frequency: kFrequencyHz, seed});

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
    ({points, timings} = cursory.generateTrajectory(
        [fromX, fromY], [toX, toY],
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
  const destinationX = Math.round(toX);
  const destinationY = Math.round(toY);
  let dispatchedMs = 0;

  // The first point is where the cursor already is, and the last is the
  // destination the caller dispatches itself; both ends are excluded.
  for (let i = 1; i < points.length - 1; i++) {
    const x = Math.round(points[i][0]);
    const y = Math.round(points[i][1]);
    if (x === previousX && y === previousY)
      continue;
    // Landing on the destination early would leave the caller's own dispatch
    // with nothing to move, and the same unacked wait.
    if (x === destinationX && y === destinationY)
      continue;
    const elapsedMs = Math.round(timings[i] * scale);
    steps.push([x, y, Math.max(0, elapsedMs - dispatchedMs)]);
    dispatchedMs = elapsedMs;
    previousX = x;
    previousY = y;
  }

  const totalMs = Math.round(recordedMs * scale);
  return {steps, trailingDelayMs: Math.max(0, totalMs - dispatchedMs)};
}
