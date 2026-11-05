/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * The seeded random streams humanize engines draw from.
 *
 * One stream per input channel, derived from the launch's `humanize:seed`, so
 * the same seed and the same sequence of actions on a channel give the same
 * plans, whatever happens on the other channels and however late acks arrive.
 * The derivation is fixed, byte for byte, because launchers derive the same
 * streams on their side for client-side engines:
 *
 *   stream(channel) = Mulberry32(splitmix64(seed ^ TAG[channel]) & 0xffffffff)
 *
 * No Gecko imports: this module also runs under Node for the unit tests.
 */

const kMask64 = (1n << 64n) - 1n;

export const kChannelTags = Object.freeze({
  mouse: 0x6d6f7573n,     // "mous"
  keyboard: 0x6b657962n,  // "keyb"
  scroll: 0x7363726fn,    // "scro"
});

/** One splitmix64 output for the 64-bit state `x`. */
export function splitmix64(x) {
  let z = (BigInt.asUintN(64, x) + 0x9e3779b97f4a7c15n) & kMask64;
  z = ((z ^ (z >> 30n)) * 0xbf58476d1ce4e5b9n) & kMask64;
  z = ((z ^ (z >> 27n)) * 0x94d049bb133111ebn) & kMask64;
  return z ^ (z >> 31n);
}

/** Mulberry32 over a 32-bit seed: a function returning floats in [0, 1). */
export function mulberry32(seed) {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * A channel's stream for a 64-bit master seed, counting its draws.
 *
 * `position` is how many numbers the stream has produced, which the trace
 * records so a plan can be replayed from the middle of a session.
 */
export function channelStream(masterSeed, channel) {
  const tag = kChannelTags[channel];
  if (tag === undefined)
    throw new Error(`unknown humanize channel: ${channel}`);
  const next = mulberry32(Number(splitmix64(BigInt.asUintN(64, masterSeed) ^ tag) & 0xffffffffn));
  const stream = () => {
    stream.position++;
    return next();
  };
  stream.position = 0;
  return stream;
}

/**
 * Parse `humanize:seed`, a decimal uint64 carried as a string: Juggler reads
 * config numbers as doubles, which cannot hold every 64-bit seed exactly.
 */
export function parseSeed(text) {
  if (!/^\d{1,20}$/.test(text))
    throw new Error(`humanize:seed must be a decimal uint64, got ${JSON.stringify(text)}`);
  const seed = BigInt(text);
  if (seed > kMask64)
    throw new Error(`humanize:seed is out of the uint64 range: ${text}`);
  return seed;
}
