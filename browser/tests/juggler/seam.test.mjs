// HumanizeSeam: engine resolution from the manifest, seeded determinism,
// budget, fallback, trace.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import {test} from 'node:test';
import {JUGGLER, load} from './gecko.mjs';

const {HumanizeSeam} = await load('input/HumanizeSeam.js');
const modules = {
  'resource://gre/modules/juggler/input/CursorTrajectory.js': await load('input/CursorTrajectory.js'),
  'resource://gre/modules/juggler/input/WheelNotches.js': await load('input/WheelNotches.js'),
};
const BASE_MANIFEST = JSON.parse(fs.readFileSync(path.join(JUGGLER, '../../settings/humanize-engines.json'), 'utf-8'));

/**
 * The base manifest plus a test engine, `fancy`, on every channel and first in
 * `auto`: what a build that ships an extra engine declares.
 */
function withFancy(fancy) {
  const manifest = structuredClone(BASE_MANIFEST);
  for (const channel of ['mouse', 'keyboard', 'scroll']) {
    manifest[channel].push('fancy');
    manifest.auto[channel].unshift('fancy');
  }
  manifest.engines.fancy = {
    module: 'test:fancy',
    options: {
      budgetSeconds: {key: 'humanize:fancy:budgetSeconds', min: 1, max: 20},
      speed: {key: 'humanize:fancy:speed'},
    },
  };
  modules['test:fancy'] = {fancy};
  return manifest;
}

function config(values) {
  return {
    getString: key => (typeof values[key] === 'string' ? values[key] : ''),
    getBool: (key, fallback) => (typeof values[key] === 'boolean' ? values[key] : fallback),
    getDouble: (key, fallback) => (typeof values[key] === 'number' ? values[key] : fallback),
  };
}

function seam(values, {manifest = BASE_MANIFEST, trace = null, clock, sleep} = {}) {
  const warnings = [];
  const instance = new HumanizeSeam({
    config: config(values),
    manifest: () => manifest,
    importModule: url => modules[url],
    trace,
    clock,
    sleep,
    warn: message => warnings.push(message),
  });
  instance.warnings = warnings;
  return instance;
}

const page = {cursor: {x: 40, y: 40}, viewport: {width: 1280, height: 720}};
const TARGETS = [[900, 500], [120, 650], [1200, 30], [640, 360], [5, 700], [700, 710]];
const moveTo = (x, y) => ({kind: 'move', x, y});

/** A session: moves between targets, with wheel turns in between. */
function session(s, {wheels = true} = {}) {
  const plans = [];
  let cursor = page.cursor;
  for (const [x, y] of TARGETS) {
    plans.push(s.plan('mouse', 'planMove', {...page, cursor}, {x, y}).plan.steps);
    cursor = {x, y};
    if (wheels)
      plans.push(s.plan('scroll', 'planWheel', {}, {x, y}, {deltaX: 0, deltaY: 450, deltaZ: 0}).plan.steps);
  }
  return plans;
}

const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex').slice(0, 16);

test('resolution: channel keys, the legacy humanize flag, and auto', () => {
  const legacyOn = seam({humanize: true});
  assert.deepEqual(['mouse', 'keyboard', 'scroll'].map(c => legacyOn.resolve(c)), ['cursory', 'raw', 'notches']);
  const legacyOff = seam({});
  assert.deepEqual(['mouse', 'keyboard', 'scroll'].map(c => legacyOff.resolve(c)), ['raw', 'raw', 'raw']);
  const perChannel = seam({'humanize': true, 'humanize:mouse': 'raw', 'humanize:keyboard': 'auto', 'humanize:scroll': 'notches'});
  assert.deepEqual(['mouse', 'keyboard', 'scroll'].map(c => perChannel.resolve(c)), ['raw', 'raw', 'notches']);
});

test('humanize off never reads the manifest; humanize on requires it', () => {
  const none = values => new HumanizeSeam({config: config(values), manifest: () => null, importModule: () => ({}), warn: () => {}});
  assert.equal(none({}).plan('mouse', 'planMove', page, {x: 1, y: 1}), null);
  assert.throws(() => none({humanize: true}).resolve('mouse'), /no humanize-engines.json/);
});

test('an engine the manifest does not list for the channel fails loudly', () => {
  assert.throws(() => seam({'humanize:mouse': 'notches'}).resolve('mouse'), /does not list for mouse/);
  assert.throws(() => seam({'humanize:scroll': 'smooth'}).resolve('scroll'), /humanize:scroll names "smooth"/);
});

test('mouse:internal defaults to the resolved mouse engine', () => {
  assert.equal(seam({'humanize:mouse': 'cursory'}).resolve('mouse:internal'), 'cursory');
  assert.equal(seam({'humanize:mouse': 'raw'}).resolve('mouse:internal'), 'raw');
  assert.equal(seam({'humanize:mouse': 'raw', 'humanize:mouse:internal': 'auto'}).resolve('mouse:internal'), 'cursory');
});

test('an engine that is not available warns once and runs the last auto choice', () => {
  const s = seam({'humanize:mouse': 'fancy', 'humanize:scroll': 'fancy'}, {manifest: withFancy({available: () => false})});
  assert.equal(s.resolve('mouse'), 'cursory');
  assert.equal(s.resolve('scroll'), 'notches');
  assert.equal(s.warnings.length, 1);
  assert.match(s.warnings[0], /^humanize_engine_unavailable/);
});

test('auto takes the first available engine the manifest lists, per action', () => {
  let available = true;
  const planMove = (ctx, to) => ({steps: [{...moveTo(to.x, to.y), t: 0}], endState: {}});
  const s = seam({'humanize:mouse': 'auto'}, {manifest: withFancy({planMove, available: () => available})});
  assert.equal(s.plan('mouse', 'planMove', page, {x: 1, y: 1}).engine, 'fancy');
  available = false;
  assert.equal(s.plan('mouse', 'planMove', page, {x: 3, y: 4}).engine, 'cursory');
});

test('availability is per channel: an engine can be ready on one channel only', () => {
  const asked = [];
  const planKey = () => ({steps: [{t: 0, kind: 'key', type: 'keydown', key: 'a'}], endState: {}});
  const s = seam({'humanize': true, 'humanize:mouse': 'auto', 'humanize:mouse:internal': 'auto', 'humanize:keyboard': 'auto', 'humanize:scroll': 'fancy'},
      {manifest: withFancy({planKey, available: channel => (asked.push(channel), channel === 'keyboard')})});
  assert.equal(s.resolve('keyboard'), 'fancy');
  assert.equal(s.resolve('mouse'), 'cursory');
  assert.equal(s.resolve('mouse:internal'), 'cursory');
  assert.equal(s.resolve('scroll'), 'notches');
  assert.deepEqual([...new Set(asked)].sort(), ['keyboard', 'mouse', 'scroll']);
  assert.equal(s.active('keyboard'), true);
  assert.equal(seam({'humanize:keyboard': 'raw'}).active('keyboard'), false);
});

test('ctx.now is the seam clock at planning time, and absent without one', () => {
  let seen;
  const planKey = ctx => (seen = ctx.now, null);
  const clock = () => 1000;
  seam({'humanize:keyboard': 'fancy'}, {manifest: withFancy({planKey}), clock})
      .plan('keyboard', 'planKey', {keyboardState: {}}, {type: 'keydown', key: 'a'});
  assert.equal(seen, 1000);
  seam({'humanize:keyboard': 'fancy'}, {manifest: withFancy({planKey})})
      .plan('keyboard', 'planKey', {keyboardState: {}}, {type: 'keydown', key: 'a'});
  assert.equal(seen, undefined);
});

test('raw and engines without the command leave the stock dispatch in charge', () => {
  const s = seam({'humanize:mouse': 'raw', 'humanize:keyboard': 'raw', 'humanize:scroll': 'notches'});
  assert.equal(s.plan('mouse', 'planMove', page, {x: 5, y: 5}), null);
  assert.equal(s.plan('keyboard', 'planKey', {keyboardState: {}}, {type: 'keydown', key: 'a'}), null);
  assert.equal(s.plan('keyboard', 'planInsert', {keyboardState: {}}, 'hello'), null);
});

test('handles: whether the resolved engine plans a command, so a site can skip its probe', () => {
  assert.equal(seam({humanize: false}).handles('scroll', 'planIntoView'), false);
  assert.equal(seam({humanize: true}).handles('scroll', 'planWheel'), true);
  assert.equal(seam({humanize: true}).handles('scroll', 'planIntoView'), false, 'notches does not plan into-view');
  const manifest = withFancy({planIntoView: () => null});
  assert.equal(seam({'humanize': true, 'humanize:scroll': 'fancy'}, {manifest}).handles('scroll', 'planIntoView'), true);
  assert.equal(seam({'humanize': true, 'humanize:scroll': 'raw'}, {manifest}).handles('scroll', 'planIntoView'), false);
});

test('same seed, same plans; a different seed, different plans', () => {
  const values = {'humanize': true, 'humanize:mouse': 'cursory', 'humanize:scroll': 'notches', 'humanize:seed': '1234'};
  const first = session(seam(values));
  assert.deepEqual(session(seam(values)), first);
  assert.notDeepEqual(session(seam({...values, 'humanize:seed': '1235'})), first);
  // Pinned, so a change to the derivation or to a base planner shows up here.
  assert.equal(digest(first), '67efcf3d3ed1951c');
});

test('each channel has its own stream: scrolling does not change the mouse paths', () => {
  const values = {'humanize:mouse': 'cursory', 'humanize:scroll': 'notches', 'humanize:seed': '99'};
  const moves = plans => plans.filter(steps => steps[0].kind === 'move');
  assert.deepEqual(moves(session(seam(values), {wheels: true})), moves(session(seam(values), {wheels: false})));
});

test('an unseeded launch draws a random seed, as before', () => {
  const values = {'humanize:mouse': 'cursory', 'humanize:scroll': 'notches'};
  assert.notDeepEqual(session(seam(values)), session(seam(values)));
});

test('planners use no randomness but the channel stream', () => {
  const random = Math.random;
  Math.random = () => { throw new Error('Math.random called by a planner'); };
  try {
    session(seam({'humanize:mouse': 'cursory', 'humanize:scroll': 'notches', 'humanize:seed': '7'}));
  } finally {
    Math.random = random;
  }
});

test('cursory plans end exactly on the target, in time order, inside maxTime', () => {
  for (const maxTime of [0.3, 1.5, 4]) {
    const s = seam({'humanize:mouse': 'cursory', 'humanize:maxTime': maxTime, 'humanize:seed': '5'});
    for (let i = 0; i < 200; i++) {
      const to = {x: (i * 211) % 1280, y: (i * 97) % 720};
      const {plan, budgetMs} = s.plan('mouse', 'planMove', {...page, cursor: {x: (i * 53) % 1280, y: (i * 31) % 720}}, to);
      assert.equal(budgetMs, maxTime * 1000);
      const last = plan.steps.at(-1);
      assert.deepEqual([last.x, last.y], [to.x, to.y]);
      assert.ok(last.t <= budgetMs, `${last.t} > ${budgetMs}`);
      for (let j = 1; j < plan.steps.length; j++)
        assert.ok(plan.steps[j].t >= plan.steps[j - 1].t);
    }
  }
});

test('an untracked cursor moves straight to the target', () => {
  const {plan} = seam({'humanize:mouse': 'cursory'}).plan('mouse', 'planMove', {...page, cursor: {x: NaN, y: NaN}}, {x: 10, y: 20});
  assert.deepEqual(plan.steps, [{...moveTo(10, 20), t: 0}]);
});

test('notches carry the whole requested distance, one essential step per notch', () => {
  const s = seam({'humanize:scroll': 'notches', 'humanize:seed': '3'});
  for (const [deltaX, deltaY, count] of [[0, 100, 1], [0, 449, 4], [0, -250, 3], [120, 0, 1], [0, 30, 1], [300, -500, 5]]) {
    const {plan} = s.plan('scroll', 'planWheel', {}, {x: 1, y: 2}, {deltaX, deltaY, deltaZ: 0});
    assert.equal(plan.steps.length, count);
    assert.ok(plan.steps.every(step => step.essential && step.mode === 1));
    const lines = axis => plan.steps.reduce((sum, step) => sum + step[axis], 0);
    const expected = d => (d === 0 ? 0 : Math.sign(d) * Math.max(1, Math.round(Math.abs(d) / 100)) * 3);
    assert.deepEqual([lines('dx'), lines('dy')], [expected(deltaX), expected(deltaY)]);
    for (let i = 1; i < plan.steps.length; i++) {
      const gap = plan.steps[i].t - plan.steps[i - 1].t;
      assert.ok(gap >= 18 && gap < 60, `notch gap ${gap}`);
    }
  }
});

test('a plan over its budget is compressed to fit, and says so', () => {
  const slow = {planWheel: () => ({steps: [{t: 0}, {t: 30000}], endState: {}})};
  const s = seam({'humanize:scroll': 'fancy', 'humanize:fancy:budgetSeconds': 4}, {manifest: withFancy(slow)});
  const planned = s.plan('scroll', 'planWheel', {}, {x: 0, y: 0}, {deltaX: 0, deltaY: 100, deltaZ: 0});
  assert.equal(planned.budgetMs, 4000);
  assert.equal(planned.plan.steps.at(-1).t, 4000);
  assert.equal(planned.outcome, 'compressed');
  assert.match(s.warnings[0], /^humanize_plan_over_budget/);
});

test('an engine that throws falls back to the last auto choice for that action', () => {
  const broken = {planMove: () => { throw new Error('boom'); }};
  const s = seam({'humanize:mouse': 'fancy'}, {manifest: withFancy(broken)});
  assert.equal(s.plan('mouse', 'planMove', page, {x: 300, y: 300}).engine, 'cursory');
  assert.equal(s.plan('mouse', 'planMove', page, {x: 301, y: 300}).engine, 'cursory');
  assert.equal(s.warnings.length, 1);
  assert.match(s.warnings[0], /^humanize_engine_failed:mouse/);
});

test('an engine gets the options its manifest entry declares, from their config keys', () => {
  let seen = null;
  const fancy = {planKey: ctx => { seen = ctx.options; return null; }};
  seam({'humanize:keyboard': 'fancy', 'humanize:fancy:speed': 1.5, 'humanize:maxTime': 9}, {manifest: withFancy(fancy)})
      .plan('keyboard', 'planKey', {keyboardState: {}}, {type: 'keydown', key: 'a'});
  assert.deepEqual(seen, {speed: 1.5});
});

test('the trace records the plan, what was dispatched when, and the stream position', async () => {
  const records = [];
  let now = 0;
  const s = seam({'humanize:mouse': 'cursory', 'humanize:seed': '11'}, {
    trace: record => records.push(record),
    clock: () => now,
    sleep: async ms => { now += ms; },
  });
  for (const [x, y] of TARGETS.slice(0, 2)) {
    const planned = s.plan('mouse', 'planMove', page, {x, y});
    await s.play(planned, async () => true, {command: 'Page.dispatchMouseEvent', page: 'p1'});
  }
  assert.equal(records.length, 2);
  assert.deepEqual(records.map(r => r.seedStreamPos), [0, 2]);
  for (const record of records) {
    assert.equal(record.channel, 'mouse');
    assert.equal(record.engine, 'cursory');
    assert.equal(record.outcome, 'ok');
    assert.deepEqual(record.dispatched.map(d => d.tActual), record.plan.map(step => step.t));
  }
});
