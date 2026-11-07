// Pacer.play: every step is due at start + t, whatever the acks cost.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {play} = await load('input/Pacer.js');

/** A virtual clock: sleeping and slow dispatches advance it, nothing else. */
function virtualTime() {
  let now = 1000;
  return {
    clock: () => now,
    sleep: async ms => { now += ms; },
    spend: ms => { now += ms; },
  };
}

const plan = n => ({steps: Array.from({length: n}, (_, i) => ({t: i * 20, i}))});

test('a slow ack delays only its own step, not every step after it', async () => {
  const time = virtualTime();
  const sent = [];
  const {outcome, dispatched} = await play(plan(26), async step => {
    sent.push(time.clock() - 1000);
    time.spend(8);  // each dispatch waits 8ms for its ack
  }, time);
  assert.equal(outcome, 'ok');
  assert.deepEqual(sent, plan(26).steps.map(s => s.t));
  // Gap-after-ack pacing would have ended at 25 * (20 + 8) = 700ms.
  assert.equal(time.clock() - 1000, 500 + 8);
  assert.deepEqual(dispatched.map(d => d.tActual), sent);
});

test('a step that is already late is dispatched at once, and the schedule holds', async () => {
  const time = virtualTime();
  const sent = [];
  await play(plan(5), async (step, i) => {
    sent.push(time.clock() - 1000);
    if (i === 1)
      time.spend(50);  // one ack takes 2.5 steps
  }, time);
  assert.deepEqual(sent, [0, 20, 70, 70, 80]);
});

test('declining a step fast-forwards: the last step is still dispatched, the rest are not', async () => {
  const time = virtualTime();
  const sent = [];
  const {outcome} = await play(plan(10), async (step, i) => {
    sent.push(i);
    return i !== 3;
  }, time);
  assert.equal(outcome, 'fast_forward');
  assert.deepEqual(sent, [0, 1, 2, 3, 9]);
});

test('past the deadline, only essential steps and the end state are dispatched, without waiting', async () => {
  const time = virtualTime();
  const steps = Array.from({length: 8}, (_, i) => ({t: i * 100, essential: i % 2 === 0}));
  const sent = [];
  const {outcome} = await play({steps}, async (step, i) => {
    sent.push([i, time.clock() - 1000]);
    if (i === 2)
      time.spend(400);  // acks stall
  }, {...time, deadlineMs: 450});
  assert.equal(outcome, 'fast_forward');
  assert.deepEqual(sent, [[0, 0], [1, 100], [2, 200], [4, 600], [6, 600], [7, 600]]);
});

test('aborting stops the plan; nothing more is dispatched', async () => {
  const time = virtualTime();
  const controller = new AbortController();
  const sent = [];
  const {outcome} = await play(plan(10), async (step, i) => {
    sent.push(i);
    if (i === 4)
      controller.abort();
  }, {...time, signal: controller.signal});
  assert.equal(outcome, 'aborted');
  assert.deepEqual(sent, [0, 1, 2, 3, 4]);
});
