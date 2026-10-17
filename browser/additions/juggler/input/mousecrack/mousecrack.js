/* Juggler's entry point to mousecrack (see model.js and README.md).
 *
 * Loads the exported weights from the package on first use and generates one
 * path per call. Generation runs on the parent process's main thread, so it
 * yields to the event loop between batches of steps: a long path costs up to
 * ~100ms of compute (measured, 0.2ms a step), which must not block the UI or
 * other Juggler work.
 */

import {MousecrackModel, pathSteps, smoothPath} from './model.js';

const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');

const kBase = 'resource://gre/modules/juggler/input/mousecrack/';

// Steps computed between yields: ~5ms of work at the measured rate.
const kStepsPerSlice = 24;

function readPackagedBytes(url) {
  const channel = NetUtil.newChannel({uri: url, loadUsingSystemPrincipal: true});
  const stream = Components.classes['@mozilla.org/binaryinputstream;1']
      .createInstance(Components.interfaces.nsIBinaryInputStream);
  stream.setInputStream(channel.open());
  try {
    // Read in a loop: a jar stream need not make a whole entry available at once.
    const chunks = [];
    let total = 0;
    for (let available = stream.available(); available > 0; available = stream.available()) {
      const chunk = new Uint8Array(stream.readByteArray(available));
      chunks.push(chunk);
      total += chunk.length;
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return bytes;
  } finally {
    stream.close();
  }
}

let model = null;

function loadModel() {
  if (!model) {
    const manifest = JSON.parse(new TextDecoder().decode(readPackagedBytes(kBase + 'model.json')));
    const bytes = readPackagedBytes(kBase + 'model.bin');
    model = new MousecrackModel(new Float32Array(bytes.buffer, 0, bytes.length / 4), manifest);
  }
  return model;
}

const yieldToEventLoop = () => new Promise(resolve => Services.tm.dispatchToMainThread(resolve));

async function generateSliced(start, end) {
  const steps = pathSteps(loadModel(), start, end);
  let count = 0;
  let result = steps.next();
  while (!result.done) {
    if (++count % kStepsPerSlice === 0)
      await yieldToEventLoop();
    result = steps.next();
  }
  return result.value;
}

/**
 * A human-like path from `from` to `to` ([x, y] each), smoothed as upstream's
 * move() does, as `{points: [[x, y], ...], timings: [ms, ...], converged}`.
 */
export async function generateTrajectory(from, to) {
  const {path, converged} = await generateSliced({x: from[0], y: from[1]}, {x: to[0], y: to[1]});
  const smoothed = smoothPath(path, 7);
  return {
    points: smoothed.map(p => [p.x, p.y]),
    timings: smoothed.map(p => p.t),
    converged,
  };
}
