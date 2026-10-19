/**
 * PCG64 (XSL-RR 128/64), ported from numpy/random/src/pcg64/pcg64.h.
 *
 * © 2014 Melissa O'Neill, © 2015 Robert Kern. MIT licensed, as vendored by numpy.
 */

import { generateState64, intToUint32Array, mixEntropy } from './seedSequence.js';

const MASK64 = 0xffffffffffffffffn;
const MASK128 = (1n << 128n) - 1n;
const MULTIPLIER = (2549297995355413924n << 64n) + 4865540595714422341n;

/** 2**-53, numpy's uint64 -> double conversion factor. */
const DOUBLE_SCALE = 1.0 / 9007199254740992.0;

export class Pcg64 {
  constructor(initialState, initialSequence) {
    this.state = 0n;

    // next_uint32 hands out a 64-bit draw in two halves; the unused half is held here.
    this.hasSpareUint32 = false;
    this.spareUint32 = 0;

    this.increment = ((initialSequence << 1n) | 1n) & MASK128;
    this.step();
    this.state = (this.state + initialState) & MASK128;
    this.step();
  }

  step() {
    this.state = (this.state * MULTIPLIER + this.increment) & MASK128;
  }

  nextUint64() {
    this.step();
    const state = this.state;
    const value = ((state >> 64n) ^ state) & MASK64;
    const rotation = (state >> 122n) & 63n;
    return ((value >> rotation) | (value << ((64n - rotation) & 63n))) & MASK64;
  }

  nextUint32() {
    if (this.hasSpareUint32) {
      this.hasSpareUint32 = false;
      return this.spareUint32;
    }
    const next = this.nextUint64();
    this.hasSpareUint32 = true;
    this.spareUint32 = Number(next >> 32n);
    return Number(next & 0xffffffffn);
  }

  nextDouble() {
    return Number(this.nextUint64() >> 11n) * DOUBLE_SCALE;
  }
}

/**
 * Build the bit generator `np.random.default_rng(seed)` would build.
 *
 * Passing no seed draws 128 bits of OS entropy, matching numpy's `randbits(128)`.
 */
export function createPcg64(seed) {
  const entropy = intToUint32Array(seed === undefined ? randomEntropy() : toSeedInteger(seed));
  const state = generateState64(mixEntropy(entropy), 4);
  return new Pcg64((state[0] << 64n) | state[1], (state[2] << 64n) | state[3]);
}

function toSeedInteger(seed) {
  if (typeof seed === 'bigint') {
    return seed;
  }
  if (!Number.isSafeInteger(seed)) {
    throw new RangeError(
      'seed must be a safe integer or a bigint; larger seeds lose precision as a number',
    );
  }
  return BigInt(seed);
}

// CAMOUFOX: upstream draws its entropy from node:crypto's randomBytes. This runs
// in the browser's parent process, where the Web Crypto API is the equivalent
// source -- both are the OS CSPRNG, and the bytes are consumed identically.
function randomEntropy() {
  let value = 0n;
  for (const byte of crypto.getRandomValues(new Uint8Array(16))) {
    value = (value << 8n) | BigInt(byte);
  }
  return value;
}
