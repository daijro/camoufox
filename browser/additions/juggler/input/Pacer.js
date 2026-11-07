/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * Plays a humanize plan on its own schedule. The one pacing rule for every
 * engine.
 *
 * Each step carries `t`, milliseconds from the start of the action, and waits
 * until `start + t`, not a gap after the previous step's ack. Waiting a full
 * gap after each ack added every ack's latency to the action: on a page busy
 * 19ms in every 20, moves planned at 0.5s took 0.54-0.71s
 * (browser/tests/playwright/patches/humanize-pacing.py). A late ack delays only its own step; the
 * ones after it are still due on the original clock.
 *
 * No Gecko imports at module scope: this module also runs under Node for the
 * unit tests, with `clock` and `sleep` supplied.
 */

let geckoSleep = null;

function defaultSleep(ms, signal) {
  if (!geckoSleep) {
    const {setTimeout, clearTimeout} = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
    geckoSleep = (waitMs, abortSignal) => new Promise(resolve => {
      const timer = setTimeout(done, waitMs);
      function done() {
        clearTimeout(timer);
        abortSignal?.removeEventListener('abort', done);
        resolve();
      }
      abortSignal?.addEventListener('abort', done);
    });
  }
  return geckoSleep(ms, signal);
}

/**
 * @param {{steps: Array<{t: number, essential?: boolean}>}} plan
 * @param {(step: object, index: number) => Promise<boolean|void>} dispatchStep
 *   dispatches one step. Returning `false` gives up on the rest of the timing:
 *   the plan fast-forwards to its end state (below).
 * @param {object} options
 * @param {AbortSignal} [options.signal] stops the plan; nothing more dispatches.
 * @param {number} [options.deadlineMs] once this long has passed since the
 *   start, the plan fast-forwards: acks stalling must not hold the process-wide
 *   input slot for long.
 * @returns {Promise<{outcome: 'ok'|'fast_forward'|'aborted',
 *   dispatched: Array<{i: number, tPlanned: number, tActual: number}>}>}
 *
 * Fast-forwarding skips the waits and every remaining step that is not
 * `essential`, but always dispatches the last step: a move still ends exactly
 * on its target, and a step that carries part of the requested effect (a wheel
 * notch, a key) is still delivered.
 */
export async function play(plan, dispatchStep, {
  signal = null,
  deadlineMs = Infinity,
  clock = () => ChromeUtils.now(),
  sleep = defaultSleep,
} = {}) {
  const {steps} = plan;
  const start = clock();
  const dispatched = [];
  let outcome = 'ok';

  const dispatch = async (i) => {
    const tActual = clock() - start;
    const result = await dispatchStep(steps[i], i);
    dispatched.push({i, tPlanned: steps[i].t, tActual});
    return result;
  };

  for (let i = 0; i < steps.length; i++) {
    if (signal?.aborted)
      return {outcome: 'aborted', dispatched};
    if (outcome === 'ok') {
      const wait = Math.min(steps[i].t, deadlineMs) - (clock() - start);
      if (wait > 0) {
        await sleep(wait, signal);
        if (signal?.aborted)
          return {outcome: 'aborted', dispatched};
      }
      if (clock() - start >= deadlineMs)
        outcome = 'fast_forward';
    }
    if (outcome === 'fast_forward') {
      if (i === steps.length - 1 || steps[i].essential)
        await dispatch(i);
      continue;
    }
    if (await dispatch(i) === false)
      outcome = 'fast_forward';
  }
  return {outcome, dispatched};
}
