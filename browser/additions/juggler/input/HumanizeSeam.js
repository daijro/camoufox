/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * The humanize engine seam: which engine handles an input action, and how its
 * plan is played.
 *
 * Humanization intercepts the stock Juggler input commands Playwright already
 * sends, so the same Playwright script drives every build. Each command site in
 * PageHandler asks the seam for a plan; `null` means the stock dispatch runs.
 * The seam owns everything that is not modelling: engine resolution per
 * channel, the seeded streams (HumanizeRng.js), the time budget, pacing
 * (Pacer.js) and the trace. An engine is a pure planner:
 *
 *   planMove(ctx, to)                  Page.dispatchMouseEvent mousemove
 *   planWheel(ctx, at, delta)          Page.dispatchWheelEvent
 *   planIntoView(ctx, probe)           Page.scrollIntoViewIfNeeded, in rounds
 *   planKey(ctx, keyEvent)             Page.dispatchKeyEvent
 *   planInsert(ctx, text)              Page.insertText
 *
 * Each returns `{steps, endState}` or `null` to decline. A planIntoView plan
 * that ends in a `probe` step asks for another round with a fresh probe. Steps carry `t`, ms
 * from the start of the action, non-decreasing; a planner uses no randomness
 * but `ctx.rng` and reads no clock: `ctx.now` is the time the action was
 * planned at, for engines that pace against earlier actions. An engine may
 * implement any subset, and may also define `available(channel)` (false: not
 * usable on that channel right now) and `budgetMs(options)` (its own time
 * budget).
 *
 * Which engines exist is the build's humanize-engines.json (docs/humanize.md),
 * beside properties.json: the engines each channel may name, what `auto`
 * tries in order, and per engine the module that exports it and the config
 * keys its options arrive in. Nothing here names an engine.
 */

import {channelStream, parseSeed} from './HumanizeRng.js';
import {play} from './Pacer.js';

const kManifestName = 'humanize-engines.json';

const kChannelKeys = {
  'mouse': 'humanize:mouse',
  'mouse:internal': 'humanize:mouse:internal',
  'keyboard': 'humanize:keyboard',
  'scroll': 'humanize:scroll',
};

const kDefaultBudgetSeconds = 8;

/**
 * Past this multiple of its budget, a plan whose acks are stalling
 * fast-forwards to its end state. Mouse and wheel plans hold the process-wide
 * activation slot while they play (kActivationSlotBudgetMs, 30s).
 */
const kDeadlineFactor = 1.5;

const geckoConfig = {
  getString: key => ChromeUtils.camouGetString(key),
  getBool: (key, fallback) => ChromeUtils.camouGetBool(key, fallback),
  getDouble: (key, fallback) => ChromeUtils.camouGetDouble(key, fallback),
};

/** humanize-engines.json beside the binary, or null if the build has none. */
function loadGeckoManifest() {
  const file = Services.dirsvc.get('GreD', Components.interfaces.nsIFile);
  file.append(kManifestName);
  if (!file.exists())
    return null;
  const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');
  const stream = NetUtil.newChannel({uri: Services.io.newFileURI(file), loadUsingSystemPrincipal: true}).open();
  try {
    return JSON.parse(NetUtil.readInputStreamToString(stream, stream.available(), {charset: 'UTF-8'}));
  } finally {
    stream.close();
  }
}

function geckoTraceSink() {
  const path = Services.env.get('CAMOU_HUMANIZE_TRACE');
  if (!path)
    return null;
  let pending = Promise.resolve();
  return record => {
    const line = JSON.stringify(record) + '\n';
    pending = pending.then(() => IOUtils.writeUTF8(path, line, {mode: 'appendOrCreate'}));
    return pending;
  };
}

function randomSeed() {
  return crypto.getRandomValues(new BigUint64Array(1))[0];
}

const streamChannel = channel => (channel === 'mouse:internal' ? 'mouse' : channel);

export class HumanizeSeam {
  /**
   * Everything the seam reads from the browser is injectable, so the Node unit
   * tests run the same code: `config` (camoucfg reads), `manifest` (a function
   * returning the parsed humanize-engines.json, or null), `importModule`,
   * `trace` (a record sink or null), `clock` and `sleep`.
   */
  constructor({config, manifest, importModule, trace, clock, sleep, warn}) {
    this._config = config;
    this._loadManifest = manifest;
    this._manifest = undefined;
    this._importModule = importModule;
    this._modules = new Map();
    this._trace = trace;
    this._pacing = {clock, sleep};
    this._warn = warn;
    this._warned = new Set();
    this._streams = new Map();
    const seedText = config.getString('humanize:seed');
    this._seed = seedText ? parseSeed(seedText) : randomSeed();
  }

  _warnOnce(code, detail) {
    if (this._warned.has(code))
      return;
    this._warned.add(code);
    this._warn(`${code}: ${detail}`);
  }

  get manifest() {
    if (this._manifest === undefined) {
      this._manifest = this._loadManifest();
      if (!this._manifest)
        throw new Error(`humanize is on, but this build has no ${kManifestName}`);
    }
    return this._manifest;
  }

  _engine(name) {
    let engine = this._modules.get(name);
    if (!engine) {
      const entry = this.manifest.engines?.[name];
      engine = entry && this._importModule(entry.module)[name];
      if (!engine)
        throw new Error(`${kManifestName} lists "${name}" but gives no module that exports it`);
      this._modules.set(name, engine);
    }
    return engine;
  }

  _usable(name, channel) {
    return name === 'raw' || this._engine(name).available?.(streamChannel(channel)) !== false;
  }

  /** The last `auto` choice: what an unusable or failing engine falls back to. */
  _fallback(channel) {
    return this.manifest.auto?.[streamChannel(channel)]?.at(-1) ?? 'raw';
  }

  /**
   * The engine name for `channel` (or `mouse:internal`) for the action about to
   * run. Resolved per action, not per launch: an engine that stops being
   * available falls back at the next action.
   */
  resolve(channel) {
    let name = this._config.getString(kChannelKeys[channel]);
    if (!name) {
      if (channel === 'mouse:internal')
        return this.resolve('mouse');
      // A launcher that predates the channel keys sends only `humanize`, which
      // meant cursory mouse plus notched wheel: the base `auto`.
      name = this._config.getBool('humanize', false) ? 'auto' : 'raw';
    }
    if (name === 'raw')
      return name;
    if (name === 'auto')
      return (this.manifest.auto?.[streamChannel(channel)] ?? []).find(n => this._usable(n, channel)) ?? 'raw';
    if (!(this.manifest[streamChannel(channel)] ?? []).includes(name))
      throw new Error(`${kChannelKeys[channel]} names "${name}", which ${kManifestName} does not list for ${streamChannel(channel)}`);
    if (!this._usable(name, channel)) {
      const fallback = this._fallback(channel);
      this._warnOnce('humanize_engine_unavailable', `${channel} runs ${fallback}: ${name} is not available`);
      return fallback;
    }
    return name;
  }

  /**
   * Whether `channel` has an engine other than `raw` for the next action. A
   * command site checks this before gathering context that only an engine
   * needs, such as what has focus.
   */
  active(channel) {
    return this.resolve(channel) !== 'raw';
  }

  /**
   * Whether the engine for `channel`'s next action implements `method`. A
   * command site checks this before a round trip that only such an engine
   * needs, such as the scroll probe.
   */
  handles(channel, method) {
    const name = this.resolve(channel);
    return name !== 'raw' && typeof this._engine(name)[method] === 'function';
  }

  _stream(channel) {
    let stream = this._streams.get(streamChannel(channel));
    if (!stream) {
      stream = channelStream(this._seed, streamChannel(channel));
      this._streams.set(streamChannel(channel), stream);
    }
    return stream;
  }

  _options(name) {
    // camouGetDouble takes a finite default, and cannot say a key is absent;
    // the launchers never send a negative option, so this one marks it.
    const unset = -Number.MAX_VALUE;
    const options = {};
    for (const [option, {key}] of Object.entries(this.manifest.engines?.[name]?.options ?? {})) {
      const value = this._config.getDouble(key, unset);
      if (value !== unset)
        options[option] = value;
    }
    return options;
  }

  /**
   * Plan one action. Returns null when the stock dispatch should run: the
   * channel is `raw`, or its engine does not handle this command, or declined.
   *
   * @param {string} channel mouse | mouse:internal | keyboard | scroll
   * @param {string} method the engine method, e.g. 'planMove'
   * @param {object} context per-page state: cursor, viewport, keyboardState
   * @param {...any} args the method's own arguments
   */
  plan(channel, method, context, ...args) {
    const name = this.resolve(channel);
    if (name === 'raw')
      return null;
    const planned = this._planWith(name, channel, method, context, args);
    if (planned !== undefined)
      return planned;
    // The engine threw. This action falls back.
    const fallback = this._fallback(channel);
    if (fallback === name || fallback === 'raw')
      return null;
    return this._planWith(fallback, channel, method, context, args) ?? null;
  }

  _planWith(name, channel, method, context, args) {
    const engine = this._engine(name);
    if (!engine[method])
      return null;
    const options = this._options(name);
    const budgetMs = engine.budgetMs?.(options) ??
        (options.budgetSeconds ?? kDefaultBudgetSeconds) * 1000;
    const rng = this._stream(channel);
    const seedStreamPos = rng.position;
    const ctx = {...context, channel, rng, options, budgetMs, seed: this._seed, now: this._pacing.clock?.()};
    let plan;
    try {
      plan = engine[method](ctx, ...args);
    } catch (e) {
      this._warnOnce(`humanize_engine_failed:${channel}`, `${name}.${method} threw ${e}`);
      return undefined;
    }
    if (!plan)
      return null;
    let outcome = 'ok';
    const endMs = plan.steps.at(-1)?.t ?? 0;
    if (endMs > budgetMs) {
      // A plan must finish well inside Playwright's action timeout, which the
      // browser cannot see. Compress rather than truncate: the end of a plan is
      // where it lands on its target.
      const scale = budgetMs / endMs;
      plan = {...plan, steps: plan.steps.map(step => ({...step, t: step.t * scale}))};
      outcome = 'compressed';
      this._warnOnce('humanize_plan_over_budget', `${name}.${method} planned ${Math.round(endMs)}ms against ${budgetMs}ms`);
    }
    return {channel, engine: name, method, plan, budgetMs, seedStreamPos, outcome};
  }

  /**
   * Play a plan from plan() with `dispatchStep` (see Pacer.play), and trace it.
   *
   * @param {object} meta {command, page, signal} for the trace and cancellation.
   */
  async play(planned, dispatchStep, {command, page, signal = null} = {}) {
    const {outcome, dispatched} = await play(planned.plan, dispatchStep, {
      signal,
      deadlineMs: planned.budgetMs * kDeadlineFactor,
      ...(this._pacing.clock ? {clock: this._pacing.clock} : {}),
      ...(this._pacing.sleep ? {sleep: this._pacing.sleep} : {}),
    });
    if (outcome === 'fast_forward')
      this._warnOnce('humanize_fast_forward', `${planned.engine}.${planned.method} ran past ${planned.budgetMs * kDeadlineFactor}ms`);
    await this._trace?.({
      ts: Date.now(),
      page,
      channel: planned.channel,
      engine: planned.engine,
      command,
      seedStreamPos: planned.seedStreamPos,
      budgetMs: planned.budgetMs,
      plan: planned.plan.steps,
      dispatched,
      outcome: outcome === 'ok' ? planned.outcome : outcome,
    });
    return outcome;
  }
}

let processSeam = null;

/** The seam for this browser process, created on first use. */
export function humanizeSeam() {
  if (!processSeam) {
    processSeam = new HumanizeSeam({
      config: geckoConfig,
      manifest: loadGeckoManifest,
      importModule: url => ChromeUtils.importESModule(url),
      trace: geckoTraceSink(),
      clock: () => ChromeUtils.now(),
      warn: message => dump(`[juggler] WARN ${message}\n`),
    });
  }
  return processSeam;
}
