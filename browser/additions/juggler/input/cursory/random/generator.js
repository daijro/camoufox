/**
 * The slice of `numpy.random.Generator` that Cursory draws from, ported from
 * numpy/random/src/distributions/distributions.c and numpy/random/_generator.pyx.
 *
 * Every method consumes the bit generator in exactly the order numpy does, so a
 * seeded run here draws the same numbers as a seeded run of the Python original.
 */

import { searchSortedRight } from '../numeric.js';
import { createPcg64 } from './pcg64.js';
import {
  FI_DOUBLE,
  KI_DOUBLE,
  WI_DOUBLE,
  ZIGGURAT_NOR_INV_R,
  ZIGGURAT_NOR_R,
} from './ziggurat.js';

const UINT32_MAX = 0xffffffff;

export class Generator {
  constructor(bitGenerator) {
    this.bitGenerator = bitGenerator;
  }

  /** `Generator.random()`. */
  random() {
    return this.bitGenerator.nextDouble();
  }

  /** `Generator.uniform(low, high)`. */
  uniform(low, high) {
    const range = high - low;
    if (!Number.isFinite(range)) {
      throw new RangeError('Range exceeds valid bounds');
    }
    return low + range * this.bitGenerator.nextDouble();
  }

  /** `Generator.uniform(low, high, size)`. */
  uniformArray(low, high, size) {
    const range = high - low;
    if (!Number.isFinite(range)) {
      throw new RangeError('Range exceeds valid bounds');
    }
    const out = new Float64Array(size);
    for (let i = 0; i < size; i += 1) {
      out[i] = low + range * this.bitGenerator.nextDouble();
    }
    return out;
  }

  /** `Generator.normal(loc, scale)`. */
  normal(loc, scale) {
    if (scale < 0) {
      throw new RangeError('scale < 0');
    }
    return loc + scale * this.standardNormal();
  }

  /** `Generator.normal(size=size)`, i.e. `loc` 0 and `scale` 1. */
  standardNormalArray(size) {
    const out = new Float64Array(size);
    for (let i = 0; i < size; i += 1) {
      out[i] = this.standardNormal();
    }
    return out;
  }

  /**
   * `random_standard_normal`: the 256-layer ziggurat, including its two rejection
   * paths. The paths draw extra doubles, so they have to be reproduced to keep
   * the stream aligned, not just the returned value.
   */
  standardNormal() {
    for (;;) {
      let draw = this.bitGenerator.nextUint64();
      const index = Number(draw & 0xffn);
      draw >>= 8n;
      const sign = draw & 0x1n;
      const magnitude = (draw >> 1n) & 0x000fffffffffffffn;

      let x = Number(magnitude) * WI_DOUBLE[index];
      if (sign === 1n) {
        x = -x;
      }
      if (magnitude < KI_DOUBLE[index]) {
        return x;
      }

      if (index === 0) {
        // Sample the tail beyond ZIGGURAT_NOR_R.
        for (;;) {
          const xx = -ZIGGURAT_NOR_INV_R * Math.log1p(-this.bitGenerator.nextDouble());
          const yy = -Math.log1p(-this.bitGenerator.nextDouble());
          if (yy + yy > xx * xx) {
            return (magnitude >> 8n) & 0x1n ? -(ZIGGURAT_NOR_R + xx) : ZIGGURAT_NOR_R + xx;
          }
        }
      }

      const wedge =
        (FI_DOUBLE[index - 1] - FI_DOUBLE[index]) * this.bitGenerator.nextDouble() +
        FI_DOUBLE[index];
      if (wedge < Math.exp(-0.5 * x * x)) {
        return x;
      }
    }
  }

  /**
   * `Generator.integers(high)`: a uniform integer in [0, high).
   *
   * numpy picks a strategy per range width; Cursory only ever asks for ranges that
   * fit in 32 bits, so only that branch (Lemire's method) is implemented. Wider
   * ranges would silently take a different number of draws, so they raise instead.
   */
  integers(high) {
    if (!Number.isInteger(high) || high <= 0) {
      throw new RangeError('high must be a positive integer');
    }
    const range = high - 1;
    if (range === 0) {
      return 0;
    }
    if (range > UINT32_MAX) {
      throw new RangeError('ranges wider than 2**32 are not supported');
    }
    if (range === UINT32_MAX) {
      return this.bitGenerator.nextUint32();
    }
    return this.boundedLemire32(range);
  }

  /** `buffered_bounded_lemire_uint32`. */
  boundedLemire32(range) {
    const rangeExclusive = BigInt(range + 1);
    let scaled = BigInt(this.bitGenerator.nextUint32()) * rangeExclusive;
    let leftover = scaled & 0xffffffffn;

    if (leftover < rangeExclusive) {
      const threshold = BigInt((UINT32_MAX - range) % (range + 1));
      while (leftover < threshold) {
        scaled = BigInt(this.bitGenerator.nextUint32()) * rangeExclusive;
        leftover = scaled & 0xffffffffn;
      }
    }
    return Number(scaled >> 32n);
  }

  /** `Generator.choice(len(weights), p=weights)`. */
  choice(weights) {
    const cumulative = new Float64Array(weights.length);
    let running = 0;
    for (let i = 0; i < weights.length; i += 1) {
      running += weights[i];
      cumulative[i] = running;
    }
    const total = cumulative[cumulative.length - 1];
    for (let i = 0; i < cumulative.length; i += 1) {
      cumulative[i] /= total;
    }
    return searchSortedRight(cumulative, this.bitGenerator.nextDouble());
  }
}

/** The equivalent of `np.random.default_rng(seed)`. */
export function defaultGenerator(seed) {
  return new Generator(createPcg64(seed));
}
