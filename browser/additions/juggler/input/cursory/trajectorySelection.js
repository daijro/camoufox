/** Port of `cursory/trajectory_selection.py`. */

import { LOADED_TRAJECTORIES } from './data.js';
import { argSortTopN, EPSILON, hypot, searchSortedRight, sum } from './numeric.js';

export { LOADED_TRAJECTORIES };

const TRAJECTORY_COUNT = LOADED_TRAJECTORIES.length;

function endpointDelta(trajectory, axis) {
  const { points } = trajectory;
  return points[points.length - 1][axis] - points[0][axis];
}

/** Straight-line displacement of each recording, and its direction as a unit vector. */
const TRAJECTORIES_DX = Float64Array.from(LOADED_TRAJECTORIES, (t) => endpointDelta(t, 0));
const TRAJECTORIES_DY = Float64Array.from(LOADED_TRAJECTORIES, (t) => endpointDelta(t, 1));
const TRAJECTORIES_DISPLACEMENTS = Float64Array.from(TRAJECTORIES_DX, (dx, i) =>
  hypot(dx, TRAJECTORIES_DY[i]),
);
const TRAJECTORIES_NORM_DX = Float64Array.from(TRAJECTORIES_DX, (dx, i) =>
  TRAJECTORIES_DISPLACEMENTS[i] === 0 ? 0 : dx / TRAJECTORIES_DISPLACEMENTS[i],
);
const TRAJECTORIES_NORM_DY = Float64Array.from(TRAJECTORIES_DY, (dy, i) =>
  TRAJECTORIES_DISPLACEMENTS[i] === 0 ? 0 : dy / TRAJECTORIES_DISPLACEMENTS[i],
);
const TRAJECTORIES_LENGTHS = Float64Array.from(LOADED_TRAJECTORIES, (t) => t.length);

/**
 * Displacement over path length: 1 for a perfectly straight recording, lower the
 * more the hand wandered. Sorted so a candidate's efficiency can be ranked
 * against every recording rather than against its own handful of rivals.
 */
const TRAJECTORIES_EFFICIENCIES = Float64Array.from(TRAJECTORIES_DISPLACEMENTS, (displacement, i) =>
  TRAJECTORIES_LENGTHS[i] > 0 ? displacement / TRAJECTORIES_LENGTHS[i] : 1,
);
const SORTED_TRAJECTORY_EFFICIENCIES = Float64Array.from(TRAJECTORIES_EFFICIENCIES).sort();

/**
 * The `topN` recordings closest to the target in direction and in length.
 */
export function findNearestTrajectory(
  targetStart,
  targetEnd,
  { directionWeight = 0.8, lengthWeight = 0.2, topN = 5 } = {},
) {
  const dxTarget = targetEnd[0] - targetStart[0];
  const dyTarget = targetEnd[1] - targetStart[1];
  const lengthTarget = hypot(dxTarget, dyTarget);

  if (lengthTarget === 0) {
    return argSortTopN(TRAJECTORIES_LENGTHS, topN).map((index) => LOADED_TRAJECTORIES[index]);
  }

  const normDxTarget = dxTarget / lengthTarget;
  const normDyTarget = dyTarget / lengthTarget;
  const scores = new Float64Array(TRAJECTORY_COUNT);

  for (let i = 0; i < TRAJECTORY_COUNT; i += 1) {
    // Cosine distance: 0 for the same heading, 2 for the opposite one.
    const directionDistance =
      1 - (TRAJECTORIES_NORM_DX[i] * normDxTarget + TRAJECTORIES_NORM_DY[i] * normDyTarget);
    const lengthDifferenceRatio =
      Math.abs(TRAJECTORIES_DISPLACEMENTS[i] - lengthTarget) / Math.max(lengthTarget, 1);
    scores[i] = directionWeight * directionDistance + lengthWeight * lengthDifferenceRatio;
  }

  return argSortTopN(scores, topN).map((index) => LOADED_TRAJECTORIES[index]);
}

/**
 * Pick a direction-, distance- and efficiency-appropriate recording.
 *
 * The pool is widened by re-querying around jittered endpoints, then one
 * candidate is drawn at random with a soft preference for the requested
 * directness. Unusually direct and unusually wandering paths stay possible.
 */
export function findClosestTrajectory(
  targetStart,
  targetEnd,
  rng,
  {
    numNearestToSample = 5,
    randomSampleIterations = 20,
    directness = 0.65,
  } = {},
) {
  const dxTarget = targetEnd[0] - targetStart[0];
  const dyTarget = targetEnd[1] - targetStart[1];
  const lengthTarget = hypot(dxTarget, dyTarget);
  if (!(directness >= 0 && directness <= 1)) {
    throw new RangeError('directness must be between zero and one');
  }

  const candidates = findNearestTrajectory(targetStart, targetEnd, { topN: numNearestToSample });
  const jitter = lengthTarget * 0.1;
  for (let iteration = 0; iteration < randomSampleIterations; iteration += 1) {
    const perturbedEnd = [
      targetEnd[0] + rng.uniform(-jitter, jitter),
      targetEnd[1] + rng.uniform(-jitter, jitter),
    ];
    candidates.push(
      ...findNearestTrajectory(targetStart, perturbedEnd, { topN: numNearestToSample }),
    );
  }

  // Rank each candidate's efficiency against every recording, so the preference
  // means the same thing whatever direction and distance was asked for.
  const preferredRank = 0.2 + 0.75 * directness;
  const weights = new Float64Array(candidates.length);
  for (let i = 0; i < candidates.length; i += 1) {
    const candidate = candidates[i];
    const displacement = hypot(endpointDelta(candidate, 0), endpointDelta(candidate, 1));
    const efficiency = candidate.length > 0 ? displacement / candidate.length : 1;
    const rank =
      searchSortedRight(SORTED_TRAJECTORY_EFFICIENCIES, efficiency) / TRAJECTORY_COUNT;

    const offset = (rank - preferredRank) / 0.2;
    const core = Math.exp(-0.5 * (offset * offset));
    // A small lift at both tails keeps the extremes reachable without making
    // either of them the default.
    const centeredRank = 2 * rank - 1;
    const tailFloor = 0.05 * (1 + 0.1 * Math.abs(centeredRank) ** 3);
    weights[i] = core + tailFloor;
  }

  const total = sum(weights);
  for (let i = 0; i < weights.length; i += 1) {
    weights[i] /= total;
  }

  return { trajectory: candidates[rng.choice(weights)], dxTarget, dyTarget, lengthTarget };
}

/**
 * Scale, rotate and translate a path so it runs exactly from `targetStart` to
 * `targetEnd` while keeping its shape.
 */
export function morphTrajectory(
  points,
  targetStart,
  targetEnd,
  dxTarget,
  dyTarget,
  lengthTarget,
) {
  const start = points[0];
  const end = points[points.length - 1];

  const dxOriginal = end[0] - start[0];
  const dyOriginal = end[1] - start[1];
  const lengthOriginal = Math.sqrt(dxOriginal * dxOriginal + dyOriginal * dyOriginal);
  const scale = lengthOriginal !== 0 ? lengthTarget / lengthOriginal : 1.0;

  const rotation = Math.atan2(dyTarget, dxTarget) - Math.atan2(dyOriginal, dxOriginal);
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);

  const morphed = points.map((point) => {
    const x = (point[0] - start[0]) * scale;
    const y = (point[1] - start[1]) * scale;
    return [x * cos - y * sin + targetStart[0], x * sin + y * cos + targetStart[1]];
  });

  // Land on the requested endpoints exactly rather than within a rounding error.
  morphed[0] = [targetStart[0], targetStart[1]];
  morphed[morphed.length - 1] = [targetEnd[0], targetEnd[1]];
  return morphed;
}

/**
 * Nudge each point sideways by a drifting amount.
 *
 * The offsets are correlated from point to point, so the path wavers the way a
 * hand does instead of buzzing back and forth across the ideal line.
 */
export function jitterTrajectory(points, trajectoryLength, rng, scale = 0.01) {
  const count = points.length;
  const lengthScale = Math.min(1.0, trajectoryLength / 400);

  // Spacing around each point, used to keep the jitter proportional to how fast
  // the cursor was moving there.
  const gaps = new Float64Array(Math.max(count - 1, 0));
  for (let i = 0; i < count - 1; i += 1) {
    const dx = points[i + 1][0] - points[i][0];
    const dy = points[i + 1][1] - points[i][1];
    gaps[i] = Math.sqrt(dx * dx + dy * dy);
  }

  const adaptiveScales = new Float64Array(count);
  for (let i = 0; i < count; i += 1) {
    const averageGap = ((i > 0 ? gaps[i - 1] : 0) + (i < count - 1 ? gaps[i] : 0)) / 2;
    adaptiveScales[i] = scale * (averageGap / Math.max(averageGap, 1)) * lengthScale;
  }

  // Unit normal at each point, from the local tangent.
  //
  // On whole-pixel input the normals are truncated towards zero, leaving only
  // 0 and +/-1. That is not a simplification: numpy types an array of recorded
  // integer coordinates as int64, so the original's `np.zeros_like(tangents)`
  // is an integer array and storing a unit vector in it rounds it off. Most
  // recordings in the database are whole-pixel, so this shapes most of the
  // jitter Cursory actually produces, and dropping it would put this port on a
  // different path from the Python original for the same seed.
  const quantizeNormals = isWholePixelPath(points);
  const normalX = new Float64Array(count);
  const normalY = new Float64Array(count);
  for (let i = 0; i < count; i += 1) {
    const ahead = i === count - 1 ? points[count - 1] : points[Math.min(i + 1, count - 1)];
    const behind = i === 0 ? points[0] : points[Math.max(i - 1, 0)];
    const tangentX = ahead[0] - behind[0];
    const tangentY = ahead[1] - behind[1];
    const tangentLength = Math.sqrt(tangentX * tangentX + tangentY * tangentY);
    if (tangentLength > EPSILON) {
      normalX[i] = -tangentY / tangentLength;
      normalY[i] = tangentX / tangentLength;
      if (quantizeNormals) {
        normalX[i] = Math.trunc(normalX[i]);
        normalY[i] = Math.trunc(normalY[i]);
      }
    }
  }

  const innovations = rng.standardNormalArray(count);
  const correlation = 0.75;
  const innovationScale = Math.sqrt(1 - correlation * correlation);

  const jittered = new Array(count);
  let lateralOffset = 0;
  for (let i = 0; i < count; i += 1) {
    lateralOffset =
      i === 0 ? innovations[0] : correlation * lateralOffset + innovationScale * innovations[i];
    const displacement = lateralOffset * adaptiveScales[i];
    jittered[i] = [
      points[i][0] + normalX[i] * displacement,
      points[i][1] + normalY[i] * displacement,
    ];
  }
  return jittered;
}

/**
 * A random point inside the rectangle spanned by two corners, pulled towards the
 * middle by a Gaussian.
 */
export function generateMiddleBiasedPoint(x1, y1, x2, y2, rng, biasFactor = 2.0) {
  const minX = Math.min(x1, x2);
  const maxX = Math.max(x1, x2);
  const minY = Math.min(y1, y2);
  const maxY = Math.max(y1, y2);

  const offsetX = rng.normal(0, (maxX - minX) / (2 * biasFactor));
  const offsetY = rng.normal(0, (maxY - minY) / (2 * biasFactor));

  return [
    Math.max(minX, Math.min(maxX, (minX + maxX) / 2 + offsetX)),
    Math.max(minY, Math.min(maxY, (minY + maxY) / 2 + offsetY)),
  ];
}

/**
 * Bend the path towards a few random points, as if the hand had drifted on its
 * way across. Displacements are square-rooted so near points are pulled far less
 * than the raw pull would suggest.
 */
export function knotTrajectory(
  points,
  targetStart,
  targetEnd,
  rng,
  numKnots = 5,
  knotStrength = 0.15,
) {
  const count = points.length;
  const offsetX = new Float64Array(count);
  const offsetY = new Float64Array(count);

  for (let knotIndex = 0; knotIndex < numKnots; knotIndex += 1) {
    const knot = generateMiddleBiasedPoint(
      targetStart[0],
      targetStart[1],
      targetEnd[0],
      targetEnd[1],
      rng,
    );

    const toKnotX = new Float64Array(count);
    const toKnotY = new Float64Array(count);
    const distances = new Float64Array(count);
    let maxDistance = -Infinity;
    for (let i = 0; i < count; i += 1) {
      toKnotX[i] = knot[0] - points[i][0];
      toKnotY[i] = knot[1] - points[i][1];
      distances[i] = Math.sqrt(toKnotX[i] * toKnotX[i] + toKnotY[i] * toKnotY[i]);
      if (distances[i] > maxDistance) {
        maxDistance = distances[i];
      }
    }
    if (maxDistance < 1e-6) {
      continue;
    }

    for (let i = 0; i < count; i += 1) {
      const scaling = (1.0 - distances[i] / maxDistance) * knotStrength;
      offsetX[i] += toKnotX[i] * scaling;
      offsetY[i] += toKnotY[i] * scaling;
    }
  }

  return points.map((point, i) => [
    point[0] + signedSqrt(offsetX[i]),
    point[1] + signedSqrt(offsetY[i]),
  ]);
}

/** Whether numpy would have typed these coordinates as integers rather than floats. */
function isWholePixelPath(points) {
  return points.every((point) => Number.isInteger(point[0]) && Number.isInteger(point[1]));
}

/** `np.copysign(np.sqrt(np.abs(x)), x)`. */
function signedSqrt(value) {
  const root = Math.sqrt(Math.abs(value));
  return value < 0 ? -root : root;
}

/**
 * Select a recording for this movement, then jitter, knot and morph it onto the
 * requested endpoints.
 */
export function findTrajectory(targetStart, targetEnd, rng, directness = 0.65) {
  const { trajectory, dxTarget, dyTarget, lengthTarget } = findClosestTrajectory(
    targetStart,
    targetEnd,
    rng,
    { directness },
  );

  // A recording replayed over a shorter distance should not take as long as it
  // originally did. Square-root scaling keeps very short movements long enough
  // to still be sampled at a normal polling rate.
  const recordedLength = trajectory.length;
  let timings = [...trajectory.timing];
  if (lengthTarget > 0 && lengthTarget < recordedLength) {
    const timeScale = Math.sqrt(lengthTarget / recordedLength);
    const startTime = timings[0];
    timings = timings.map((timing) => startTime + (timing - startTime) * timeScale);
  }

  const jittered = jitterTrajectory(trajectory.points, lengthTarget, rng);
  const knotted = knotTrajectory(jittered, targetStart, targetEnd, rng);
  const points = morphTrajectory(knotted, targetStart, targetEnd, dxTarget, dyTarget, lengthTarget);
  return { points, timings };
}
