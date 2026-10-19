/**
 * numpy's SeedSequence, ported from numpy/random/bit_generator.pyx (BSD-3-Clause).
 *
 * Cursory's Python original seeds itself with `np.random.default_rng(seed)`, so a
 * seed only reproduces the same trajectory here if it expands into the same
 * bit-generator state. That expansion is this file.
 */

const INIT_A = 0x43b0d7e5;
const MULT_A = 0x931e8875;
const INIT_B = 0x8b51f9dd;
const MULT_B = 0x58f38ded;
const MIX_MULT_L = 0xca01f9dd;
const MIX_MULT_R = 0x4973f715;
const XSHIFT = 16;

/** numpy's DEFAULT_POOL_SIZE. */
export const POOL_SIZE = 4;

/** Split a non-negative integer into uint32 words, lowest bits first. */
export function intToUint32Array(value) {
  if (value < 0n) {
    throw new RangeError('seed must be a non-negative integer');
  }
  if (value === 0n) {
    return [0];
  }
  const words = [];
  let remaining = value;
  while (remaining > 0n) {
    words.push(Number(remaining & 0xffffffffn));
    remaining >>= 32n;
  }
  return words;
}

/**
 * numpy's `hashmix`. The multiplier advances on every call, so the whole mix
 * depends on how many times this has been invoked.
 */
class Hasher {
  constructor(initial) {
    this.constant = initial >>> 0;
  }

  mix(value) {
    let mixed = (value ^ this.constant) >>> 0;
    this.constant = Math.imul(this.constant, MULT_A) >>> 0;
    mixed = Math.imul(mixed, this.constant) >>> 0;
    return (mixed ^ (mixed >>> XSHIFT)) >>> 0;
  }
}

function mix(x, y) {
  const result = (Math.imul(MIX_MULT_L, x) - Math.imul(MIX_MULT_R, y)) >>> 0;
  return (result ^ (result >>> XSHIFT)) >>> 0;
}

/** numpy's `SeedSequence.mix_entropy`. */
export function mixEntropy(entropy) {
  const pool = new Uint32Array(POOL_SIZE);
  const hasher = new Hasher(INIT_A);

  for (let i = 0; i < POOL_SIZE; i += 1) {
    pool[i] = hasher.mix(i < entropy.length ? entropy[i] : 0);
  }
  for (let source = 0; source < POOL_SIZE; source += 1) {
    for (let destination = 0; destination < POOL_SIZE; destination += 1) {
      if (source !== destination) {
        pool[destination] = mix(pool[destination], hasher.mix(pool[source]));
      }
    }
  }
  for (let source = POOL_SIZE; source < entropy.length; source += 1) {
    for (let destination = 0; destination < POOL_SIZE; destination += 1) {
      pool[destination] = mix(pool[destination], hasher.mix(entropy[source]));
    }
  }
  return pool;
}

/** numpy's `SeedSequence.generate_state(wordCount, uint64)`. */
export function generateState64(pool, wordCount) {
  const words = new Uint32Array(wordCount * 2);
  let constant = INIT_B;

  for (let i = 0; i < words.length; i += 1) {
    let value = pool[i % pool.length];
    value = (value ^ constant) >>> 0;
    constant = Math.imul(constant, MULT_B) >>> 0;
    value = Math.imul(value, constant) >>> 0;
    words[i] = (value ^ (value >>> XSHIFT)) >>> 0;
  }

  // numpy views the uint32 words as little-endian uint64s.
  const state = new BigUint64Array(wordCount);
  for (let i = 0; i < wordCount; i += 1) {
    state[i] = BigInt(words[2 * i]) | (BigInt(words[2 * i + 1]) << 32n);
  }
  return state;
}
