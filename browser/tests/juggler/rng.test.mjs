// HumanizeRng: the per-channel streams. The launchers derive the same streams
// for client-side engines, so the vectors below are a cross-language contract.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {splitmix64, mulberry32, channelStream, parseSeed} = await load('input/HumanizeRng.js');

test('splitmix64 matches the reference outputs', () => {
  // Vigna's splitmix64.c from state 0: the first output, and the second (state
  // advanced by the golden gamma once).
  assert.equal(splitmix64(0n), 0xe220a8397b1dcdafn);
  assert.equal(splitmix64(0x9e3779b97f4a7c15n), 0x6e789e6aa1b965f4n);
});

test('mulberry32 matches the reference outputs', () => {
  const next = mulberry32(0);
  assert.deepEqual([next(), next(), next()].map(x => Math.round(x * 2 ** 32)),
      [1144304738, 1416247, 958946056]);
});

test('the same seed gives the same stream, per channel', () => {
  for (const channel of ['mouse', 'keyboard', 'scroll']) {
    const a = channelStream(1234n, channel);
    const b = channelStream(1234n, channel);
    const draws = Array.from({length: 100}, () => a());
    assert.deepEqual(Array.from({length: 100}, () => b()), draws);
    assert.equal(a.position, 100);
  }
});

test('channels and seeds give independent streams', () => {
  const first = s => s();
  const values = [
    first(channelStream(1234n, 'mouse')),
    first(channelStream(1234n, 'keyboard')),
    first(channelStream(1234n, 'scroll')),
    first(channelStream(1235n, 'mouse')),
  ];
  assert.equal(new Set(values).size, values.length);
});

test('stream derivation is pinned', () => {
  // Computed by an independent Python implementation of the derivation.
  const pinned = Object.fromEntries(['mouse', 'keyboard', 'scroll'].map(c => {
    const s = channelStream(1234n, c);
    return [c, Math.round(s() * 2 ** 32)];
  }));
  assert.deepEqual(pinned, PINNED);
});

test('seeds are decimal uint64 strings', () => {
  assert.equal(parseSeed('0'), 0n);
  assert.equal(parseSeed('18446744073709551615'), 2n ** 64n - 1n);
  for (const bad of ['', '-1', '1.5', '0x10', '18446744073709551616', ' 1'])
    assert.throws(() => parseSeed(bad), /humanize:seed/);
});

const PINNED = {mouse: 833145829, keyboard: 912731910, scroll: 1748142523};

test('the launchers\' vectors are what this module produces', async () => {
  // browser/tests/humanize/rng-vectors.json is what the Python and TypeScript
  // launchers' client-side streams are tested against.
  const fs = await import('node:fs');
  const {OUT, vectors} = await import('./gen-rng-vectors.mjs');
  assert.deepEqual(JSON.parse(fs.readFileSync(OUT, 'utf8')), vectors());
});
