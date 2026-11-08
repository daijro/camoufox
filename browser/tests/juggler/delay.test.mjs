// HumanDelay: the normal draw, its mean and spread, and its bounds.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {normalDelay, logNormalDelay} = await load('input/HumanDelay.js');

// mulberry32: the draws stay the same from run to run.
function seeded(seed) {
  return () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 2 ** 32;
  };
}

function draws(n, mean, sd, min = 0, max = Infinity) {
  const random = seeded(1234);
  return Array.from({length: n}, () => normalDelay(mean, sd, min, max, random));
}

test('draws centre on the mean with the given spread', () => {
  const xs = draws(20000, 110, 30, -Infinity, Infinity);
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((a, b) => a + (b - mean) ** 2, 0) / xs.length);
  assert.ok(Math.abs(mean - 110) < 1, `mean ${mean}`);
  assert.ok(Math.abs(sd - 30) < 1, `sd ${sd}`);
});

test('a draw never falls under the minimum nor over the maximum', () => {
  const xs = draws(20000, 110, 30, 50, 180);
  assert.equal(Math.min(...xs), 50);
  assert.equal(Math.max(...xs), 180);
});

test('without a maximum the upper tail is kept', () => {
  assert.ok(Math.max(...draws(20000, 110, 30, 50)) > 200);
});

test('the same stream gives the same delays', () => {
  assert.deepEqual(draws(5, 110, 30, 50), draws(5, 110, 30, 50));
});

test('log-normal delays are right-skewed around their median', () => {
  const random = seeded(1234);
  const xs = Array.from({length: 20000}, () => logNormalDelay(100, 0.5, 0, Infinity, random));
  const sorted = [...xs].sort((a, b) => a - b);
  const median = (sorted[9999] + sorted[10000]) / 2;
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  assert.ok(Math.abs(median - 100) < 2, `median ${median}`);
  assert.ok(mean > median, `mean ${mean} should exceed median ${median}`);
});

test('log-normal delays respect their bounds and repeat from one stream', () => {
  const random = seeded(1234);
  const xs = Array.from({length: 20000}, () => logNormalDelay(110, 0.32, 70, 180, random));
  assert.equal(Math.min(...xs), 70);
  assert.equal(Math.max(...xs), 180);
  const a = seeded(9), b = seeded(9);
  assert.deepEqual(
    Array.from({length: 5}, () => logNormalDelay(95, 0.42, 50, Infinity, a)),
    Array.from({length: 5}, () => logNormalDelay(95, 0.42, 50, Infinity, b)),
  );
});
