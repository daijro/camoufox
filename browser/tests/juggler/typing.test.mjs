// Typing at a person's rate: the key draws, and the order typeKeys presses
// and releases keys in.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {keyHold, keyInterval, typeKeys} = await load('input/HumanDelay.js');

// mulberry32: the draws stay the same from run to run.
function seeded(seed) {
  return () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 2 ** 32;
  };
}

function moments(xs) {
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((a, b) => a + (b - mean) ** 2, 0) / xs.length);
  const median = [...xs].sort((a, b) => a - b)[xs.length >> 1];
  return {mean, sd, median};
}

test('key holds and intervals have the study\'s means and spreads, right-skewed', () => {
  const random = seeded(1234);
  for (const [draw, mean, sd] of [[keyHold, 116.25, 23.88], [keyInterval, 238.66, 111.6]]) {
    const m = moments(Array.from({length: 50000}, () => draw(random)));
    assert.ok(Math.abs(m.mean - mean) < mean / 50, `mean ${m.mean}, want ${mean}`);
    assert.ok(Math.abs(m.sd - sd) < sd / 20, `sd ${m.sd}, want ${sd}`);
    assert.ok(m.mean > m.median, `mean ${m.mean} should exceed median ${m.median}`);
  }
});

test('no key interval piles up on its floor', () => {
  const random = seeded(1234);
  const xs = Array.from({length: 50000}, () => keyInterval(random));
  const floor = Math.min(...xs);
  assert.ok(floor >= 60, `an interval of ${floor} ms, under the study's 60 ms bound`);
  const atFloor = xs.filter(x => x === floor).length;
  assert.ok(atFloor < xs.length / 100, `${atFloor} of ${xs.length} intervals are exactly ${floor} ms`);
});

// Types `text` on a clock that only the typing's own waits move.
async function typed(text, seed) {
  let now = 0;
  const events = [];
  const keys = [...text].map(character => ({character, shifted: /[A-Z!?]/.test(character)}));
  await typeKeys(keys, {
    press: key => events.push({type: 'down', key, at: now}),
    release: key => events.push({type: 'up', key, at: now}),
    random: seeded(seed),
    clock: () => now,
    sleep: async ms => { now += ms; },
  });
  return events;
}

test('every typed key goes down in order and comes up once', async () => {
  const text = 'Hello there, World!';
  const events = await typed(text, 7);
  assert.equal(events.filter(e => e.type === 'down').map(e => e.key.character).join(''), text);
  for (const key of new Set(events.map(e => e.key))) {
    const [down, up] = events.filter(e => e.key === key);
    assert.deepEqual([down.type, up.type], ['down', 'up']);
  }
});

test('a press never comes the instant the key before it is up', async () => {
  const events = await typed('the quick brown fox jumps over the lazy dog', 7);
  events.forEach((e, i) => {
    if (e.type === 'down' && i > 0)
      assert.notEqual(events[i - 1].at, e.at, `${e.key.character} pressed as ${events[i - 1].key.character} came up`);
  });
});

test('a press due before the key before it is up rolls over it', async () => {
  const events = await typed('the quick brown fox jumps over the lazy dog', 7);
  let held = 0;
  let rolled = 0;
  for (const e of events) {
    if (e.type === 'down' && held)
      rolled++;
    held += e.type === 'down' ? 1 : -1;
  }
  assert.ok(rolled > 0, 'no key went down while another was held');
});

test('no key is held across a press under Shift, nor pressed while one is', async () => {
  const events = await typed('aB cDe Fg!h', 3);
  let held = [];
  for (const e of events) {
    if (e.type === 'down') {
      assert.ok(!held.length || !(e.key.shifted || held.some(k => k.shifted)),
        `${e.key.character} pressed while ${held.map(k => k.character)} held`);
      held.push(e.key);
    } else {
      held = held.filter(k => k !== e.key);
    }
  }
});
