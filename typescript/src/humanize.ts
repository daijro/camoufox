/**
 * Per-channel humanized input, run by the driver, never by the browser.
 * The TypeScript twin of python/src/camoufox/humanize.py.
 *
 *     import { Camoufox, custom, raw } from "camoufox";
 *
 *     const browser = await Camoufox({
 *       humanize: { mouse: custom(myMouse), scroll: raw(), seed: 1234 },
 *     });
 *
 * The browser has no humanization of its own: each Playwright input call
 * reaches the page as the one native-looking event it asks for, when it is
 * sent (docs/input-dispatch.md). A channel (mouse, keyboard, scroll) is either
 * raw(), Playwright's own calls unchanged, or custom(fn), a function in this
 * process that plans the channel's input and plays it through Playwright's own
 * input methods, with schedule pacing and a seeded stream
 * (_humanize_custom.ts). `humanize` itself may be null / false (every channel
 * raw), or an object per channel plus an optional `seed`; an omitted channel
 * is raw. Nothing about it reaches the browser's config.
 */

import { pyRepr, ValueError } from "./pycompat.js";

export const CHANNELS = ["mouse", "keyboard", "scroll"] as const;
export type Channel = (typeof CHANNELS)[number];

export interface Engine {
	engine: "raw" | "custom";
	options: Record<string, never>;
	fn?: CustomEngine;
}

/** What a custom() function gets after its channel's own arguments. */
export interface EngineTools {
	/** Runs Playwright's own behaviour for the call. */
	original: (...args: any[]) => Promise<any>;
	/** The channel's seeded stream. */
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
	| false
	| Record<string, unknown>
	| null
	| undefined;

/** Playwright's own dispatch, byte for byte. */
export function raw(): Engine {
	return { engine: "raw", options: {} };
}

/**
 * A client-side engine: `fn` plans the channel's input in this process and
 * plays it through Playwright. Its signature, per channel:
 *
 *     mouse     fn(page, x, y, { original, rng, play })
 *     keyboard  fn(page, text, { original, rng, play, kind })
 *     scroll    fn(page, target, { original, rng, play })   target: a Locator or [dx, dy]
 *
 * Each wheel step is one wheel event, in whole notches as a physical wheel
 * turns: 100 px is one notch, rounded, at least one, all of a step's notches
 * in that one event. A macOS identity turns in 16 px lines instead
 * (docs/input-dispatch.md). A person's scroll is several steps.
 */
export function custom(fn: CustomEngine): Engine {
	if (typeof fn !== "function")
		throw new ValueError(
			`custom() takes the function that plans the input, got ${String(fn)}`,
		);
	return { engine: "custom", options: {}, fn };
}

const IN_BROWSER =
	"the browser no longer humanizes input: each Playwright call is one event. " +
	"Humanize in the driver, with custom(fn) per channel (camoufox.humanize) or a driver-level library";

function asEngine(channel: string, value: unknown): Engine {
	const candidate =
		typeof value === "string" ? { engine: value, options: {} } : value;
	if (
		!candidate ||
		typeof candidate !== "object" ||
		typeof (candidate as { engine?: unknown }).engine !== "string"
	)
		throw new ValueError(
			`humanize["${channel}"] must be raw() or custom(fn), got ${String(value)}`,
		);
	const entry = candidate as {
		engine: string;
		options?: Record<string, unknown>;
		fn?: CustomEngine;
	};
	const hasOptions = Object.keys(entry.options ?? {}).length > 0;
	if (entry.engine === "custom") {
		if (typeof entry.fn !== "function")
			throw new ValueError(
				`humanize["${channel}"]: a custom engine needs its function, as custom(fn)`,
			);
		if (hasOptions)
			throw new ValueError(
				`humanize["${channel}"]: custom() takes no options; the function is the engine`,
			);
		return { engine: "custom", options: {}, fn: entry.fn };
	}
	if (entry.engine !== "raw")
		throw new ValueError(
			`humanize["${channel}"]: "${entry.engine}" is not an engine; ${IN_BROWSER}`,
		);
	if (hasOptions)
		throw new ValueError(`humanize["${channel}"]: raw() takes no options`);
	return raw();
}

/** The engine per channel of a `humanize` setting, and the seed if given. */
export function normalize(humanize: unknown): {
	engines: Record<Channel, Engine>;
	seed?: number | bigint;
} {
	if (humanize === null || humanize === undefined || humanize === false)
		return {
			engines: Object.fromEntries(CHANNELS.map((c) => [c, raw()])) as Record<
				Channel,
				Engine
			>,
		};
	if (typeof humanize !== "object" || Array.isArray(humanize))
		throw new ValueError(`humanize=${pyRepr(humanize)}: ${IN_BROWSER}`);
	const setting = humanize as Record<string, unknown>;
	const unknown = Object.keys(setting).filter(
		(key) => !(CHANNELS as readonly string[]).includes(key) && key !== "seed",
	);
	if (unknown.length)
		throw new ValueError(
			`humanize has no channel ${JSON.stringify(unknown)}; the channels are ${CHANNELS.join(", ")} and "seed"`,
		);
	const seed = (setting.seed ?? undefined) as number | bigint | undefined;
	if (Number.isInteger(seed) && !Number.isSafeInteger(seed))
		throw new ValueError(
			`humanize.seed ${String(seed)} is past what a number holds exactly; pass a bigint`,
		);
	if (
		seed !== undefined &&
		(!(typeof seed === "bigint" || Number.isInteger(seed)) ||
			seed < 0 ||
			BigInt(seed) >= 2n ** 64n)
	)
		throw new ValueError(
			`humanize.seed must be an integer in [0, 2**64), got ${String(seed)}`,
		);
	const engines = Object.fromEntries(
		CHANNELS.map((c) => [
			c,
			asEngine(c, setting[c] === undefined ? "raw" : setting[c]),
		]),
	) as Record<Channel, Engine>;
	return { engines, seed };
}

/** The functions of a `humanize` setting's custom channels, by channel. */
export function customEngines(
	humanize: unknown,
): Partial<Record<Channel, CustomEngine>> {
	const { engines } = normalize(humanize);
	return Object.fromEntries(
		CHANNELS.filter((c) => engines[c].engine === "custom").map((c) => [
			c,
			engines[c].fn,
		]),
	);
}

// The seeded streams, one per channel, the same in the Python launcher
// (browser/tests/humanize/rng-vectors.json pins both):
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
 * [0, 1), bit for bit what the Python launcher's stream returns; `position` counts the
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
		throw new ValueError(`unknown humanize channel: ${channel}`);
	return SeededRng(Number(BigInt.asUintN(32, splitmix64(BigInt(seed) ^ tag))));
}
