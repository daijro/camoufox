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

// How long a person holds a key, and how long from one key's press to the
// next: 116.25 ms (SD 23.88) and 238.66 ms (SD 111.60), both right-skewed
// (skewness 0.8 and 1.98), press to press never under about 60 ms (Dhakal et
// al., "Observations on Typing from 136 Million Keystrokes", CHI 2018). These
// log-normals have those means and SDs; a normal draw has no skew, and its
// floor caught 8% of the intervals.
export const keyHold = (random = Math.random) => logNormalDelay(113.87, 0.2033, 50, Infinity, random);
export const keyInterval = (random = Math.random) => logNormalDelay(216.19, 0.4447, 60, Infinity, random);

/**
 * Types `keys` at a person's rate: each goes down a keyInterval after the press
 * before it and comes up a keyHold after its own. A press due while a key is
 * still down goes down first, as a person rolls over (a quarter of keystrokes
 * in the study), unless either key is `shifted`: each key comes up under the
 * Shift it went down with. `press(key)` and `release(key)` dispatch, `clock()` reads
 * the time in ms and `sleep(ms)` waits.
 */
export async function typeKeys(keys, {press, release, clock, sleep, random = Math.random}) {
  const until = t => (t > clock() ? sleep(t - clock()) : undefined);
  const held = [];
  const releaseDue = async by => {
    while (held.length && held[0].upAt <= by) {
      const {key, upAt} = held.shift();
      await until(upAt);
      await release(key);
    }
  };
  let dueAt = clock();
  try {
    for (const key of keys) {
      await releaseDue(key.shifted || held.some(h => h.key.shifted) ? Infinity : dueAt);
      await until(dueAt);
      const started = clock();
      await press(key);
      held.push({key, upAt: clock() + keyHold(random)});
      held.sort((a, b) => a.upAt - b.upAt);
      dueAt = started + keyInterval(random);
    }
  } finally {
    await releaseDue(Infinity);
  }
}
