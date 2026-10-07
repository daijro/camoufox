/**
 * The numeric primitives Cursory's Python original gets from numpy and `math`.
 *
 * These are not general-purpose reimplementations: each one reproduces the exact
 * evaluation order of the routine it replaces, because the trajectory a seed
 * produces depends on it.
 */

/** `np.finfo(float).eps`. */
export const EPSILON = 2.220446049250313e-16;

const DBL_MIN = 2.2250738585072014e-308;

// Veltkamp splitter, 2**27 + 1.
const SPLITTER = 134217729;

const SCRATCH = new DataView(new ArrayBuffer(8));

/**
 * `math.hypot(x, y)`, following CPython's `vector_norm`.
 *
 * `Math.hypot` is not a substitute: it disagrees with CPython on about a third
 * of inputs, by up to 2 ulp. numpy's `np.hypot` is a third implementation again,
 * within 1 ulp of this one. Cursory uses both, and the distance between the
 * endpoints feeds every later step, so this stands in for each.
 */
export function hypot(x, y) {
  const first = Math.abs(x);
  const second = Math.abs(y);
  const foundNan = Number.isNaN(first) || Number.isNaN(second);

  // Built up with `>` rather than Math.max so that a NaN coordinate does not
  // hide an infinite one: hypot(inf, nan) is inf, not NaN.
  let max = 0.0;
  if (first > max) {
    max = first;
  }
  if (second > max) {
    max = second;
  }

  if (max === Infinity) {
    return Infinity;
  }
  if (foundNan) {
    return NaN;
  }
  if (max === 0) {
    return max;
  }

  const maxExponent = frexpExponent(max);
  if (maxExponent < -1023) {
    // ldexp(1.0, -maxExponent) would overflow; renormalise the subnormals first.
    return DBL_MIN * hypot(first / DBL_MIN, second / DBL_MIN);
  }
  const scale = 2 ** -maxExponent;

  let compensatedSum = 1.0;
  let productResidue = 0.0;
  let sumResidue = 0.0;

  for (const coordinate of [first, second]) {
    const scaled = coordinate * scale;
    // Lossless square, then lossless accumulation.
    const square = scaled * scaled;
    const squareLow = twoProductResidue(scaled, scaled, square);
    const sum = compensatedSum + square;
    sumResidue += compensatedSum - sum + square;
    compensatedSum = sum;
    productResidue += squareLow;
  }

  let root = Math.sqrt(compensatedSum - 1.0 + (productResidue + sumResidue));
  const square = -root * root;
  const squareLow = twoProductResidue(-root, root, square);
  const sum = compensatedSum + square;
  sumResidue += compensatedSum - sum + square;
  compensatedSum = sum;
  productResidue += squareLow;

  // Differential correction.
  root += (compensatedSum - 1.0 + (productResidue + sumResidue)) / (2.0 * root);
  return root / scale;
}

/** The exact residual of `x * y`, i.e. what `fma(x, y, -product)` returns. */
function twoProductResidue(x, y, product) {
  const xSplit = SPLITTER * x;
  const xHigh = xSplit - (xSplit - x);
  const xLow = x - xHigh;
  const ySplit = SPLITTER * y;
  const yHigh = ySplit - (ySplit - y);
  const yLow = y - yHigh;
  return xHigh * yHigh - product + xHigh * yLow + xLow * yHigh + xLow * yLow;
}

/** The exponent `frexp` reports: `value === mantissa * 2 ** exponent`, 0.5 <= |mantissa| < 1. */
function frexpExponent(value) {
  SCRATCH.setFloat64(0, value);
  const biased = (SCRATCH.getUint32(0) >>> 20) & 0x7ff;
  if (biased === 0) {
    // Subnormal: scale into the normal range and correct.
    SCRATCH.setFloat64(0, value * 2 ** 64);
    return (((SCRATCH.getUint32(0) >>> 20) & 0x7ff) - 1022) - 64;
  }
  return biased - 1022;
}

/**
 * `np.sum` over a float64 array: numpy's pairwise summation, whose rounding
 * differs from a running total.
 */
export function sum(values, start = 0, count = values.length - start) {
  if (count === 0) {
    // numpy reduces an empty array to its identity, +0.0, not to the -0.0 the
    // short loop below would start from.
    return 0;
  }
  if (count < 8) {
    // numpy starts from -0.0 so that summing only -0.0 preserves the sign.
    let total = -0.0;
    for (let i = 0; i < count; i += 1) {
      total += values[start + i];
    }
    return total;
  }

  if (count <= 128) {
    const accumulators = [
      values[start],
      values[start + 1],
      values[start + 2],
      values[start + 3],
      values[start + 4],
      values[start + 5],
      values[start + 6],
      values[start + 7],
    ];
    let i = 8;
    for (; i < count - (count % 8); i += 8) {
      for (let lane = 0; lane < 8; lane += 1) {
        accumulators[lane] += values[start + i + lane];
      }
    }
    let total =
      accumulators[0] + accumulators[1] + (accumulators[2] + accumulators[3]) +
      (accumulators[4] + accumulators[5] + (accumulators[6] + accumulators[7]));
    for (; i < count; i += 1) {
      total += values[start + i];
    }
    return total;
  }

  // Halve, but keep the split on a multiple of the unroll factor.
  let half = Math.floor(count / 2);
  half -= half % 8;
  return sum(values, start, half) + sum(values, start + half, count - half);
}

/**
 * `np.searchsorted(sorted, value, side='right')`: the index after any entries
 * equal to `value`.
 */
export function searchSortedRight(sorted, value) {
  let low = 0;
  let high = sorted.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (value < sorted[middle]) {
      high = middle;
    } else {
      low = middle + 1;
    }
  }
  return low;
}

/**
 * The first `count` indices of `np.argsort(values)`, ascending.
 *
 * Only the few best candidates are ever wanted, and this runs over a few
 * thousand scores twenty-odd times per trajectory, so it selects rather than
 * sorts.
 *
 * numpy's default sort is an unstable introsort whose order among equal scores
 * comes from whichever SIMD kernel the CPU dispatches to. This breaks ties by
 * index instead, so the same scores always produce the same ranking: scanning
 * in index order and only displacing on a strictly smaller value leaves the
 * earliest index in front.
 */
export function argSortTopN(values, count) {
  const best = [];
  for (let index = 0; index < values.length; index += 1) {
    if (best.length === count && !(values[index] < values[best[count - 1]])) {
      continue;
    }
    let position = best.length;
    while (position > 0 && values[index] < values[best[position - 1]]) {
      position -= 1;
    }
    best.splice(position, 0, index);
    if (best.length > count) {
      best.pop();
    }
  }
  return best;
}

/**
 * The integer Python's `round()` and numpy's `np.rint(...).astype(int)` produce:
 * halves go to even, unlike `Math.round`'s half-up, and there is no negative zero.
 */
export function rint(value) {
  const lower = Math.floor(value);
  const fraction = value - lower;
  let rounded;
  if (fraction > 0.5) {
    rounded = lower + 1;
  } else if (fraction < 0.5) {
    rounded = lower;
  } else {
    rounded = lower % 2 === 0 ? lower : lower + 1;
  }
  return rounded === 0 ? 0 : rounded;
}
