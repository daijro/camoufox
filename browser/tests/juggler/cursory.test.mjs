// The humanize=True planners: where a move ends and how a wheel turn divides.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {cursory} = await load('input/CursorTrajectory.js');

test('plans end exactly on the target, in time order, inside maxTime', () => {
  for (const maxTime of [0.3, 1.5, 4]) {
    const options = {maxTime};
    const budgetMs = cursory.budgetMs(options);
    assert.equal(budgetMs, maxTime * 1000);
    for (let i = 0; i < 200; i++) {
      const to = {x: (i * 211) % 1280, y: (i * 97) % 720};
      const {steps} = cursory.planMove({cursor: {x: (i * 53) % 1280, y: (i * 31) % 720}, options, rng: Math.random}, to);
      const last = steps.at(-1);
      assert.deepEqual([last.x, last.y], [to.x, to.y]);
      assert.ok(last.t <= budgetMs, `${last.t} > ${budgetMs}`);
      for (let j = 1; j < steps.length; j++)
        assert.ok(steps[j].t >= steps[j - 1].t);
    }
  }
});

test('an untracked cursor moves straight to the target', () => {
  const {steps} = cursory.planMove({cursor: {x: NaN, y: NaN}, options: {}, rng: Math.random}, {x: 10, y: 20});
  assert.deepEqual(steps, [{kind: 'move', x: 10, y: 20, t: 0}]);
});

test('a macOS turn starts at one line, grows, and carries the whole distance', () => {
  for (const [delta, total] of [[1, 1], [16, 1], [100, 6], [-1000, -63], [20000, 1250]]) {
    const {steps} = cursory.planWheel({rng: Math.random, macOS: true}, {x: 1, y: 2}, {deltaX: 0, deltaY: delta, deltaZ: 0});
    assert.equal(steps[0].dy, Math.sign(delta));
    assert.equal(steps.reduce((sum, step) => sum + step.dy, 0), total);
    assert.ok(steps.every(step => Math.abs(step.dy) <= 12 && step.mode === 1 && step.ticks.y === step.dy));
  }
});

test('notches carry the whole requested distance, one essential step per notch', () => {
  for (const [deltaX, deltaY, count] of [[0, 100, 1], [0, 449, 4], [0, -250, 3], [120, 0, 1], [0, 30, 1], [300, -500, 5]]) {
    const {steps} = cursory.planWheel({rng: Math.random}, {x: 1, y: 2}, {deltaX, deltaY, deltaZ: 0});
    assert.equal(steps.length, count);
    assert.ok(steps.every(step => step.essential && step.mode === 1));
    const lines = axis => steps.reduce((sum, step) => sum + step[axis], 0);
    const expected = d => (d === 0 ? 0 : Math.sign(d) * Math.max(1, Math.round(Math.abs(d) / 100)) * 3);
    assert.deepEqual([lines('dx'), lines('dy')], [expected(deltaX), expected(deltaY)]);
    for (let i = 1; i < steps.length; i++) {
      const gap = steps[i].t - steps[i - 1].t;
      assert.ok(gap >= 18 && gap < 60, `notch gap ${gap}`);
    }
  }
});
