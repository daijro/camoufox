/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * A person's delay in ms: a normal draw around `mean` with standard deviation
 * `sd`, never under `min` nor over `max`. Every delay Juggler waits out
 * between a person's input events (a click's hold, a key's hold, a modifier's
 * lead) is drawn here, each with the figures its caller cites.
 *
 * `random` returns floats in [0, 1); the unit tests pass a seeded stream.
 */
export function normalDelay(mean, sd, min = 0, max = Infinity, random = Math.random) {
  // Box-Muller; 1 - random() keeps the logarithm's argument above 0.
  const n = Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
  return Math.min(max, Math.max(min, mean + sd * n));
}

/**
 * A person's dwell or hold time in ms, right-skewed as human timing is: a
 * log-normal draw whose median is `medianMs`, with `sigma` the standard
 * deviation of the logarithm, clamped to [min, max]. `random` is as for
 * normalDelay.
 */
export function logNormalDelay(medianMs, sigma, min = 0, max = Infinity, random = Math.random) {
  const n = Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
  return Math.min(max, Math.max(min, medianMs * Math.exp(sigma * n)));
}
