/**
 * Per-channel humanized input, run by the driver, never by the browser.
 * The TypeScript twin of python/src/camoufox/humanize.py.
 *
 *     import { Camoufox, custom, raw } from "camoufox";
 *
 *     await Camoufox({ humanize: true });          // myuri on every channel
 *     await Camoufox({
 *       humanize: { mouse: custom(myMouse), scroll: raw(), seed: 1234 },
 *     });                                          // keyboard: myuri
 *
 * The browser has no humanization of its own: each Playwright input call
 * reaches the page as the one native-looking event it asks for, when it is
 * sent (docs/input-dispatch.md). A channel (mouse, keyboard, scroll) is one of
 *
 *     myuri()     paths, clicks, typing and wheel turns planned by myuri for
 *                 the identity's OS (the optional @jwriter20/myuri package)
 *     custom(fn)  a function in this process plans the channel's input
 *     raw()       Playwright's own calls, unchanged
 *
 * Both planners play through Playwright's own input methods, with schedule
 * pacing and a seeded stream (_humanize_custom.ts). `humanize` may be
 * null / false (every channel raw), true (every channel myuri), or an object
 * per channel plus an optional `seed`; an omitted channel is myuri. Nothing
 * about it reaches the browser's config.
 */

import { pyRepr, ValueError } from "./pycompat.js";

export const CHANNELS = ["mouse", "keyboard", "scroll"] as const;
export type Channel = (typeof CHANNELS)[number];

export interface Engine {
	engine: "raw" | "custom" | "myuri";
	options: MyuriOptions;
	fn?: CustomEngine;
}

/** What myuri() takes: `wpm` for the keyboard. */
export interface MyuriOptions {
	wpm?: number;
}

/** A box in page px, as Locator.boundingBox() gives it. */
export interface Box {
	x: number;
	y: number;
	width: number;
	height: number;
}

/** The click a mouse engine is asked for. */
export interface Click {
	button: "left" | "right" | "middle";
	clickCount: number;
	/** The element's box when the caller gave no point in it, else null. */
	box: Box | null;
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
	/** Mouse only: null for a move, else the click to press through original. */
	click?: Click | null;
}

export type CustomEngine = (page: any, ...args: any[]) => unknown;

export type HumanizeSetting =
	| boolean
	| Record<string, unknown>
	| null
	| undefined;

/** Playwright's own dispatch, byte for byte. */
export function raw(): Engine {
	return { engine: "raw", options: {} };
}

/**
 * myuri (https://github.com/JWriter20/Myuri) plans the channel's input as the
 * people it was fitted to move, click, type and scroll on the identity's OS.
 * `options` go to its planner: `wpm` for the keyboard.
 */
export function myuri(options: MyuriOptions = {}): Engine {
	const unknown = Object.keys(options).filter((key) => key !== "wpm");
	if (unknown.length)
		throw new ValueError(
			`myuri() takes no option ${JSON.stringify(unknown.sort())}; it takes wpm`,
		);
	return { engine: "myuri", options: { ...options } };
}

/**
 * A client-side engine: `fn` plans the channel's input in this process and
 * plays it through Playwright. Its signature, per channel:
 *
 *     mouse     fn(page, x, y, { original, rng, play, click })
 *     keyboard  fn(page, text, { original, rng, play, kind })
 *     scroll    fn(page, target, { original, rng, play })   target: a Locator or [dx, dy]
 *
 * For a move, `click` is null. For a click it is `{ button, clickCount, box }`,
 * `box` the element's box when the caller gave no point in it (`fn` may then
 * press anywhere in it). `fn` moves, then presses with
 * `original(x, y, { delay })`: a mouse down and up at (x, y), moving there
 * first only if the cursor is elsewhere. `delay` is how long each press is
 * held, and between the presses of a double click. A point something covers
 * rejects inside `original()`, and `fn` is called again until the timeout.
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
	"the browser does not humanize input: each Playwright call is one event. " +
	"Pass True, or myuri(), custom(fn) or raw() per channel (camoufox.humanize)";

function asEngine(channel: string, value: unknown): Engine {
	const entry = value as Partial<Engine> | null;
	if (
		typeof entry !== "object" ||
		!["myuri", "custom", "raw"].includes(entry?.engine as string)
	)
		throw new ValueError(
			`humanize["${channel}"]=${pyRepr(value)} is not an engine; ${IN_BROWSER}`,
		);
	const { engine, options = {}, fn } = entry as Engine;
	if (engine === "myuri") return myuri(options);
	if (Object.keys(options).length)
		throw new ValueError(
			`humanize["${channel}"]: ${engine}() takes no options`,
		);
	return engine === "custom" ? custom(fn as CustomEngine) : raw();
}

/** The engine per channel of a `humanize` setting, and the seed if given. */
export function normalize(humanize: unknown): {
	engines: Record<Channel, Engine>;
	seed?: number | bigint;
} {
	const every = (engine: () => Engine) => ({
		engines: Object.fromEntries(CHANNELS.map((c) => [c, engine()])) as Record<
			Channel,
			Engine
		>,
	});
	if (humanize === null || humanize === undefined || humanize === false)
		return every(raw);
	if (humanize === true) return every(myuri);
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
			asEngine(c, setting[c] === undefined ? myuri() : setting[c]),
		]),
	) as Record<Channel, Engine>;
	return { engines, seed };
}

/** The channels of a `humanize` setting that an engine in this process drives. */
export function drivenChannels(humanize: unknown): Channel[] {
	const { engines } = normalize(humanize);
	return CHANNELS.filter((c) => engines[c].engine !== "raw");
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
 * [0, 1), bit for bit what the Python launcher's stream returns.
 */
export interface SeededRng {
	(): number;
	random(): number;
}

export function SeededRng(seed32: number): SeededRng {
	let a = seed32 | 0;
	const random = () => {
		a = (a + 0x6d2b79f5) | 0;
		let t = Math.imul(a ^ (a >>> 15), 1 | a);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
	return Object.assign(() => random(), { random });
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
