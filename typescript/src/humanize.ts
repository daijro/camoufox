/**
 * Per-channel humanized input: the engine factories and the launch-time config.
 * The TypeScript twin of python/src/camoufox/humanize.py.
 *
 *     import { Camoufox } from "camoufox";
 *     import { cursory, raw } from "camoufox";
 *
 *     const browser = await Camoufox({
 *       humanize: { mouse: cursory({ max_time: 1.0 }), scroll: raw(), seed: 1234 },
 *     });
 *
 * A channel may also run a client-side engine, `custom(fn)`: a function in this
 * process plans the channel's input and plays it through Playwright's own input
 * methods, with schedule pacing and a seeded stream (_humanize_custom.ts). The
 * browser then runs that channel raw, so input is never humanized twice.
 */

import { HumanizeEngineUnavailable } from "./exceptions.js";
import { PyFloat } from "./pycompat.js";
import { LeakWarning } from "./warnings.js";

export const CHANNELS = ["mouse", "keyboard", "scroll"] as const;
export type Channel = (typeof CHANNELS)[number];

export interface Engine {
	engine: string;
	options: Record<string, number>;
	fn?: CustomEngine;
}

/** What a custom() function gets after its channel's own arguments. */
export interface EngineTools {
	/** Runs Playwright's own behaviour for the call. */
	original: (...args: any[]) => Promise<any>;
	/** The channel's seeded stream, the browser's own derivation. */
	rng: SeededRng;
	/** Dispatches steps on a schedule (validateSteps in _humanize_custom.ts). */
	play: (steps: Iterable<unknown[]>) => Promise<
		{
			i: number;
			t_planned: number;
			t_actual: number;
		}[]
	>;
	/** Keyboard only: "type", "press" or "fill". */
	kind?: "type" | "press" | "fill";
}

export type CustomEngine = (page: any, ...args: any[]) => unknown;

export type HumanizeSetting =
	| boolean
	| number
	| Record<string, unknown>
	| null
	| undefined;

export interface Manifest {
	version?: number;
	mouse?: string[];
	keyboard?: string[];
	scroll?: string[];
	auto?: Partial<Record<Channel, string[]>>;
	engines?: Record<
		string,
		{
			movesCursor?: boolean;
			options?: Record<string, { key: string; min?: number; max?: number }>;
		}
	>;
}

/** What a build without humanize-engines.json runs. */
export const LEGACY_MANIFEST: Manifest = {
	version: 0,
	mouse: ["raw", "cursory"],
	keyboard: ["raw"],
	scroll: ["raw", "cursory"],
	auto: { mouse: ["cursory"], keyboard: ["raw"], scroll: ["cursory"] },
	engines: {
		cursory: {
			options: {
				maxTime: { key: "humanize:maxTime", min: 0 },
				minTime: { key: "humanize:minTime", min: 0 },
			},
		},
	},
};

export function engine(
	name: string,
	options: Record<string, number> = {},
): Engine {
	return { engine: name, options };
}

export function auto(): Engine {
	return engine("auto");
}

export function raw(): Engine {
	return engine("raw");
}

export function cursory(
	options: { max_time?: number; min_time?: number } = {},
): Engine {
	const out: Record<string, number> = {};
	if (options.max_time !== undefined) out.maxTime = options.max_time;
	if (options.min_time !== undefined) out.minTime = options.min_time;
	return engine("cursory", out);
}

/**
 * A client-side engine: `fn` plans the channel's input in this process and
 * plays it through Playwright. Its signature, per channel:
 *
 *     mouse     fn(page, x, y, { original, rng, play })
 *     keyboard  fn(page, text, { original, rng, play, kind })
 *     scroll    fn(page, target, { original, rng, play })   target: a Locator or [dx, dy]
 *
 * Every wheel step turns in whole notches, as a physical wheel does: 100 px
 * asked is one notch, rounded, at least one per step (docs/input-dispatch.md).
 */
export function custom(fn: CustomEngine): Engine {
	if (typeof fn !== "function")
		throw new Error(
			`custom() takes the function that plans the input, got ${String(fn)}`,
		);
	return { engine: "custom", options: {}, fn };
}

function asEngine(channel: string, value: unknown): Engine {
	const candidate = typeof value === "string" ? engine(value) : value;
	if (
		!candidate ||
		typeof candidate !== "object" ||
		typeof (candidate as Engine).engine !== "string"
	)
		throw new Error(
			`humanize["${channel}"] must be an engine such as auto(), raw(), cursory() or custom(fn), got ${String(value)}`,
		);
	const entry = candidate as Engine;
	if (entry.engine === "custom") {
		if (typeof entry.fn !== "function")
			throw new Error(
				`humanize["${channel}"]: a custom engine needs its function, as custom(fn)`,
			);
		if (Object.keys(entry.options ?? {}).length)
			throw new Error(
				`humanize["${channel}"]: custom() takes no options; the function is the engine`,
			);
		return { engine: "custom", options: {}, fn: entry.fn };
	}
	const options = { ...(entry.options ?? {}) };
	for (const [key, option] of Object.entries(options)) {
		if (typeof option !== "number" || !Number.isFinite(option))
			throw new Error(
				`${entry.engine}() option ${key} must be a finite number, got ${String(option)}`,
			);
	}
	return { engine: entry.engine, options };
}

export function normalize(humanize: HumanizeSetting): {
	engines: Record<Channel, Engine>;
	seed?: number | bigint;
} {
	const allRaw = () =>
		Object.fromEntries(CHANNELS.map((c) => [c, raw()])) as Record<
			Channel,
			Engine
		>;
	if (!humanize) return { engines: allRaw() };
	if (humanize === true)
		return {
			engines: Object.fromEntries(CHANNELS.map((c) => [c, auto()])) as Record<
				Channel,
				Engine
			>,
		};
	if (typeof humanize === "number")
		return {
			engines: {
				mouse: cursory({ max_time: humanize }),
				keyboard: auto(),
				scroll: auto(),
			},
		};
	if (typeof humanize !== "object")
		throw new Error(
			`humanize must be a boolean, a number or an object, got ${String(humanize)}`,
		);
	const unknown = Object.keys(humanize).filter(
		(key) => !(CHANNELS as readonly string[]).includes(key) && key !== "seed",
	);
	if (unknown.length)
		throw new Error(
			`humanize has no channel ${JSON.stringify(unknown)}; the channels are ${CHANNELS.join(", ")} and "seed"`,
		);
	const seed = (humanize.seed ?? undefined) as number | bigint | undefined;
	if (Number.isInteger(seed) && !Number.isSafeInteger(seed))
		throw new Error(
			`humanize.seed ${String(seed)} is past what a number holds exactly; pass a bigint`,
		);
	if (
		seed !== undefined &&
		(!(typeof seed === "bigint" || Number.isInteger(seed)) ||
			seed < 0 ||
			BigInt(seed) >= 2n ** 64n)
	)
		throw new Error(
			`humanize.seed must be an integer in [0, 2**64), got ${String(seed)}`,
		);
	const engines = Object.fromEntries(
		CHANNELS.map((c) => [
			c,
			asEngine(c, humanize[c] === undefined ? "auto" : humanize[c]),
		]),
	) as Record<Channel, Engine>;
	return { engines, seed };
}

function optionKeys(
	name: string,
	options: Record<string, number>,
	manifest: Manifest,
): Record<string, PyFloat> {
	const declared = manifest.engines?.[name]?.options ?? {};
	const keys: Record<string, PyFloat> = {};
	for (const [option, value] of Object.entries(options)) {
		const spec = declared[option];
		if (!spec)
			throw new Error(
				`${name}() has no option ${option}; it takes ${Object.keys(declared).join(", ")}`,
			);
		const low = spec.min ?? 0;
		const high = spec.max;
		if (value < low || (high !== undefined && value > high))
			throw new Error(
				`${name}() ${option} must be ${high === undefined ? `at least ${low}` : `in [${low}, ${high}]`}, got ${value}`,
			);
		keys[spec.key] = new PyFloat(value);
	}
	return keys;
}

/**
 * The camoucfg keys for a `humanize` setting on a build whose
 * humanize-engines.json is `manifest` (undefined for a build without one).
 */
export function humanizeConfig(
	humanize: HumanizeSetting,
	manifest?: Manifest | null,
	iKnowWhatImDoing?: boolean,
): Record<string, unknown> {
	const { engines, seed } = normalize(humanize);
	const legacy = !manifest;
	const available = legacy ? LEGACY_MANIFEST : manifest;
	// A custom channel runs client-side, so the browser runs it raw.
	const names = Object.fromEntries(
		CHANNELS.map((c) => [
			c,
			engines[c].engine === "custom" ? "raw" : engines[c].engine,
		]),
	) as Record<Channel, string>;
	for (const channel of CHANNELS) {
		if (
			names[channel] !== "auto" &&
			names[channel] !== "raw" &&
			!(available[channel] ?? []).includes(names[channel])
		)
			throw new HumanizeEngineUnavailable(
				channel,
				names[channel],
				available[channel] ?? [],
			);
	}
	// A custom mouse plays its own moves, so only a raw one jumps.
	if (
		available.engines?.[names.scroll]?.movesCursor &&
		engines.mouse.engine === "raw"
	)
		LeakWarning.warn("humanize_scroll_teleports", iKnowWhatImDoing);
	const options: Record<string, PyFloat> = {};
	for (const channel of CHANNELS) {
		const keys = optionKeys(
			names[channel],
			engines[channel].options,
			available,
		);
		for (const [key, value] of Object.entries(keys)) {
			if (key in options && Number(options[key]) !== Number(value))
				throw new Error(
					`humanize sets ${key} twice, to ${options[key]} and ${value}`,
				);
			options[key] = value;
		}
	}
	const enabled = CHANNELS.some((c) => names[c] !== "raw");
	if (legacy) {
		const on = Object.fromEntries(
			CHANNELS.map((c) => [c, available.auto?.[c]?.[0] ?? "raw"]),
		) as Record<Channel, string>;
		const unsupported = CHANNELS.find(
			(c) => names[c] !== "auto" && names[c] !== on[c],
		);
		if (enabled && unsupported)
			throw new HumanizeEngineUnavailable(
				unsupported,
				names[unsupported],
				[on[unsupported]],
				"this build predates per-channel humanize: it runs every base engine or none",
			);
		if (seed !== undefined)
			throw new HumanizeEngineUnavailable(
				"seed",
				String(seed),
				[],
				"this build predates per-channel humanize and has no seeded input",
			);
		return enabled ? { humanize: true, ...options } : {};
	}
	// Off adds no keys: a stock identity mirror must not look like it asked for
	// humanized input. A custom mouse still needs mouse:internal, so the moves
	// the browser originates (the cursor step before a planned scroll) get a
	// humanized path, not a jump.
	const customMouse = engines.mouse.engine === "custom";
	if (!enabled && !customMouse) return {};
	const config: Record<string, unknown> = { humanize: enabled };
	for (const channel of CHANNELS)
		config[`humanize:${channel}`] = names[channel];
	if (customMouse) config["humanize:mouse:internal"] = "auto";
	Object.assign(config, options);
	if (seed !== undefined) config["humanize:seed"] = String(seed);
	return config;
}

/** The functions of a `humanize` setting's custom channels, by channel. */
export function customEngines(
	humanize: HumanizeSetting,
): Partial<Record<Channel, CustomEngine>> {
	const { engines } = normalize(humanize);
	return Object.fromEntries(
		CHANNELS.filter((c) => engines[c].engine === "custom").map((c) => [
			c,
			engines[c].fn,
		]),
	);
}

// The seeded streams. The browser draws its engines' randomness from the same
// derivation (browser/additions/juggler/input/HumanizeRng.js), so a custom engine
// gets the stream a built-in engine on that channel would:
//
//   stream(channel) = Mulberry32(splitmix64(seed ^ TAG[channel]) & 0xffffffff)

export const CHANNEL_TAGS: Record<Channel, bigint> = {
	mouse: 0x6d6f7573n,
	keyboard: 0x6b657962n,
	scroll: 0x7363726fn,
};

/** One splitmix64 output for the 64-bit state `x`. */
export function splitmix64(x: bigint): bigint {
	const mask = 2n ** 64n - 1n;
	let z = (BigInt.asUintN(64, x) + 0x9e3779b97f4a7c15n) & mask;
	z = ((z ^ (z >> 30n)) * 0xbf58476d1ce4e5b9n) & mask;
	z = ((z ^ (z >> 27n)) * 0x94d049bb133111ebn) & mask;
	return z ^ (z >> 31n);
}

/**
 * Mulberry32 over a 32-bit seed. Calling it (or `random()`) returns a float in
 * [0, 1), bit for bit what the browser's stream returns; `position` counts the
 * draws.
 */
export interface SeededRng {
	(): number;
	random(): number;
	uniform(low: number, high: number): number;
	readonly position: number;
}

export function SeededRng(seed32: number): SeededRng {
	let a = seed32 | 0;
	let position = 0;
	const random = () => {
		position += 1;
		a = (a + 0x6d2b79f5) | 0;
		let t = Math.imul(a ^ (a >>> 15), 1 | a);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
	return Object.defineProperty(
		Object.assign(() => random(), {
			random,
			uniform: (low: number, high: number) => low + (high - low) * random(),
		}),
		"position",
		{ get: () => position },
	) as SeededRng;
}

/** The stream a channel draws from for the 64-bit master `seed`. */
export function channelStream(
	seed: number | bigint,
	channel: string,
): SeededRng {
	const tag = CHANNEL_TAGS[channel as Channel];
	if (tag === undefined)
		throw new Error(`unknown humanize channel: ${channel}`);
	return SeededRng(Number(BigInt.asUintN(32, splitmix64(BigInt(seed) ^ tag))));
}
