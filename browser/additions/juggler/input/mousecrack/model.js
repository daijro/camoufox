/* mousecrack's network and path generator, run in plain JavaScript.
 *
 * Port of mousecrack's inference (https://github.com/puffinsoft/mousecrack,
 * inference/index.ts and util.ts at 6c704e4, MIT; see LICENSE here). Upstream
 * runs the model with onnxruntime-node, which Juggler cannot load, so the
 * network is evaluated here from the exported weights (model.bin, written by
 * scripts/export-mousecrack-weights.py).
 *
 * The network: two 128-unit LSTMs and a dense layer to a 5-component mixture
 * of Gaussians over the next step (dx, dy, dt). Each step's input is the
 * previous step and the distance left to the target. Upstream re-runs the
 * whole history through the LSTMs for every step; a unidirectional LSTM's
 * output for the last step depends only on its carried state, so this carries
 * the state instead. The outputs are the same, at linear rather than quadratic
 * cost.
 *
 * No browser API is used here, so tests can run this file under Node.
 */

const kUnits = 128;
const kComponents = 5;
const kOutputDims = 3;
const kParams = kComponents * (1 + 2 * kOutputDims);

// Upstream's generator constants (inference/config.ts, index.ts).
const kMinDelayMs = 2.0;
const kArrivedPx = 3.0;
export const kMaxSteps = 500;

function tensor(weights, manifest, name) {
  const t = manifest.tensors.find(entry => entry.name === name);
  const size = t.shape.reduce((a, b) => a * b, 1);
  return weights.subarray(t.offset, t.offset + size);
}

const sigmoid = x => 1 / (1 + Math.exp(-x));

/** One Keras LSTM layer (gates i, f, c, o; sigmoid and tanh), stepped. */
class LSTMLayer {
  constructor(kernel, recurrent, bias, inputs) {
    this._kernel = kernel;
    this._recurrent = recurrent;
    this._bias = bias;
    this._inputs = inputs;
    this._z = new Float64Array(4 * kUnits);
    this.h = new Float64Array(kUnits);
    this.c = new Float64Array(kUnits);
  }

  step(x) {
    const z = this._z;
    const width = 4 * kUnits;
    z.set(this._bias);
    for (let k = 0; k < this._inputs; k++) {
      const xk = x[k];
      if (xk === 0)
        continue;
      const row = k * width;
      for (let j = 0; j < width; j++)
        z[j] += xk * this._kernel[row + j];
    }
    const h = this.h;
    for (let k = 0; k < kUnits; k++) {
      const hk = h[k];
      if (hk === 0)
        continue;
      const row = k * width;
      for (let j = 0; j < width; j++)
        z[j] += hk * this._recurrent[row + j];
    }
    for (let u = 0; u < kUnits; u++) {
      const i = sigmoid(z[u]);
      const f = sigmoid(z[kUnits + u]);
      const g = Math.tanh(z[2 * kUnits + u]);
      const o = sigmoid(z[3 * kUnits + u]);
      this.c[u] = f * this.c[u] + i * g;
      h[u] = o * Math.tanh(this.c[u]);
    }
    return h;
  }
}

export class MousecrackModel {
  /**
   * @param {Float32Array} weights  model.bin
   * @param {object} manifest       model.json
   */
  constructor(weights, manifest) {
    this._weights = weights;
    this._manifest = manifest;
    this._denseKernel = tensor(weights, manifest, 'dense.kernel');
    this._denseBias = tensor(weights, manifest, 'dense.bias');
  }

  /** A fresh sequence: both LSTMs start from zero state, as upstream's do. */
  start() {
    const t = name => tensor(this._weights, this._manifest, name);
    const lstm0 = new LSTMLayer(t('lstm0.kernel'), t('lstm0.recurrent_kernel'), t('lstm0.bias'), 5);
    const lstm1 = new LSTMLayer(t('lstm1.kernel'), t('lstm1.recurrent_kernel'), t('lstm1.bias'), kUnits);
    const kernel = this._denseKernel;
    const bias = this._denseBias;
    return {
      /** The mixture parameters for the next step, given this step's input. */
      step(input) {
        const h = lstm1.step(lstm0.step(input));
        const out = new Float64Array(bias);
        for (let k = 0; k < kUnits; k++) {
          const hk = h[k];
          const row = k * kParams;
          for (let j = 0; j < kParams; j++)
            out[j] += hk * kernel[row + j];
        }
        return out;
      },
    };
  }
}

const softplus = x => (x > 20 ? x : Math.log1p(Math.exp(x)));

function randomNormal(mean, std, random) {
  const u1 = random();
  const u2 = random();
  return mean + Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2) * std;
}

/** Draw (dx, dy, dt) from the mixture: Gumbel-max component, then Gaussians. */
export function sampleStep(params, random) {
  let best = 0;
  let bestScore = -Infinity;
  for (let i = 0; i < kComponents; i++) {
    const score = params[i] - Math.log(-Math.log(random()));
    if (score > bestScore) {
      bestScore = score;
      best = i;
    }
  }
  const offset = kComponents + best * 2 * kOutputDims;
  const sample = [];
  for (let d = 0; d < kOutputDims; d++)
    sample.push(randomNormal(params[offset + d], softplus(params[offset + kOutputDims + d]), random));
  return {dx: sample[0], dy: sample[1], dt: sample[2]};
}

/**
 * A path from `start` to `end`, one model step per `next()`. The generator's
 * return value is `{path, converged}`: path is [{x, y, t}] with t in ms from the
 * start, and converged is false when the model did not come within 3px of the
 * target in kMaxSteps; upstream then jumps straight to the target, and so does
 * this, so the caller can decide what to do with such a path. Stepwise so a
 * caller on a busy thread can pause between steps.
 */
export function* pathSteps(model, start, end, random = Math.random) {
  const sequence = model.start();
  let x = start.x;
  let y = start.y;
  let dxPrev = 0;
  let dyPrev = 0;
  let dtPrev = 0;
  let elapsed = 0;
  let lastDt = kMinDelayMs;
  let converged = false;
  const path = [{x: Math.round(x), y: Math.round(y), t: 0}];

  for (let step = 0; step < kMaxSteps; step++) {
    const distX = end.x - x;
    const distY = end.y - y;
    if (Math.hypot(distX, distY) < kArrivedPx) {
      converged = true;
      break;
    }
    const {dx, dy, dt} = sampleStep(sequence.step([dxPrev, dyPrev, dtPrev, distX, distY]), random);
    const dtStep = dt > 0 ? dt : kMinDelayMs;
    x += dx;
    y += dy;
    elapsed += dtStep;
    path.push({x: Math.round(x), y: Math.round(y), t: elapsed});
    dxPrev = dx;
    dyPrev = dy;
    dtPrev = dtStep;
    lastDt = dtStep;
    yield;
  }

  elapsed += lastDt;
  path.push({x: Math.round(end.x), y: Math.round(end.y), t: elapsed});
  return {path, converged};
}

/** pathSteps run to completion. */
export function generatePath(model, start, end, random = Math.random) {
  const steps = pathSteps(model, start, end, random);
  let result = steps.next();
  while (!result.done)
    result = steps.next();
  return result.value;
}

/** Upstream's centred moving average over x and y (window 7), times untouched. */
export function smoothPath(path, window = 7) {
  if (path.length < window)
    return path;
  const half = Math.floor(window / 2);
  const out = [path[0]];
  for (let i = 1; i < path.length - 1; i++) {
    const from = Math.max(0, i - half);
    const to = Math.min(path.length, i + half + 1);
    let sumX = 0;
    let sumY = 0;
    for (let j = from; j < to; j++) {
      sumX += path[j].x;
      sumY += path[j].y;
    }
    out.push({x: Math.round(sumX / (to - from)), y: Math.round(sumY / (to - from)), t: path[i].t});
  }
  out.push(path[path.length - 1]);
  return out;
}
