/**
 * Per-channel humanized input, run by the driver, never by the browser.
 * The TypeScript twin of python/src/camoufox/humanize.py.
 *
 *     import { Camoufox, myuri, raw } from "camoufox";
 *
 *     await Camoufox({ humanize: true });          // myuri on every channel
 *     await Camoufox({
 *       humanize: {
 *         mouse: myuri({ move: myMove }),
 *         scroll: raw(),
 *         settings: { typing: { wpm: 70 } },
 *         seed: 1234,
 *       },
 *     });
 *
 * The browser has no humanization of its own: each Playwright input call
 * reaches the page as the one native-looking event it asks for, when it is
 * sent (docs/input-dispatch.md). A channel (mouse, keyboard, scroll) is one of
 *
 *     myuri()     myuri's smart actions (https://github.com/JWriter20/Myuri):
 *                 paths, clicks, typing and wheel turns as the people it was
 *                 fitted to make them on the identity's OS, and the decisions
 *                 around a click (scroll into view, the point, whether it lands)
 *     raw()       Playwright's own calls, unchanged
 *
 * cursory() is another name for myuri(), which runs cursory's paths.
 *
 * `myuri(parts)` replaces any of myuri's parts on its channel with a function
 * of yours; the rest stay myuri's (_humanize_playwright.ts). `humanize` may be
 * null / false (every channel raw), true (every channel myuri), or an object
 * per channel plus an optional `seed` and `settings`; an omitted channel is
 * myuri. `settings` are myuri's (its README lists each one), and the seed draws
 * one person around them. Nothing about it reaches the browser's config.
 */

import {
	type BoundingBox,
	type DeepPartial,
	type MyuriSettings,
	type PartContext,
	resolveSettings,
	type Vector,
} from "@jwriter20/myuri";
import { pyRepr, ValueError } from "./pycompat.js";

export const CHANNELS = ["mouse", "keyboard", "scroll"] as const;
export type Channel = (typeof CHANNELS)[number];

/** The myuri parts each channel's myuri() may replace (myuri's PARTS). */
export const CHANNEL_PARTS: Record<Channel, readonly string[]> = {
	mouse: ["move", "press", "point", "reaches"],
	keyboard: ["type", "key"],
	scroll: ["intoView", "wheel"],
};

/**
 * What myuri() takes: functions that replace myuri's parts, each called with
 * the page, the part's arguments and `{ default, rng, play }`.
 */
export interface MyuriOptions {
	move?: (page: any, x: number, y: number, ctx: PartContext<void>) => unknown;
	press?: (
		page: any,
		button: "left" | "right" | "middle",
		clickCount: number,
		ctx: PartContext<void>,
	) => unknown;
	point?: (
		page: any,
		box: BoundingBox,
		attempt: number,
		ctx: PartContext<Vector>,
	) => Vector | Promise<Vector>;
	reaches?: (
		page: any,
		locator: any,
		x: number,
		y: number,
		pressing: boolean,
		ctx: PartContext<string | null>,
	) => string | null | Promise<string | null>;
	intoView?: (page: any, locator: any, ctx: PartContext<void>) => unknown;
	wheel?: (
		page: any,
		dx: number,
		dy: number,
		ctx: PartContext<void>,
	) => unknown;
	type?: (page: any, text: string, ctx: PartContext<void>) => unknown;
	key?: (page: any, key: string, ctx: PartContext<void>) => unknown;
}

export interface Engine {
	engine: "raw" | "myuri";
	options: MyuriOptions;
}

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
 * myuri's smart actions on the channel. Each key names a part to replace with
 * your function, called as `fn(page, ...args, { default, rng, play })`:
 *
 *     mouse     move(x, y)  press(button, clickCount)  point(box, attempt)
 *               reaches(locator, x, y, pressing)
 *     keyboard  type(text)  key(key)
 *     scroll    intoView(locator)  wheel(dx, dy)
 *
 * `default(...args)` runs myuri's part (with the same arguments when given
 * none), `rng()` draws from the humanize seed's stream, and `play(steps)`
 * plays a timeline of input. Speeds and the like are `humanize.settings`.
 */
export function myuri(options: MyuriOptions = {}): Engine {
	const parts = Object.values(CHANNEL_PARTS).flat();
	const unknown = Object.keys(options)
		.filter((key) => !parts.includes(key))
		.sort();
	if (unknown.length)
		throw new ValueError(
			`myuri() has no part '${unknown[0]}'; the parts are ${JSON.stringify(CHANNEL_PARTS)} ` +
				"(speeds and the like are humanize.settings)",
		);
	for (const [name, fn] of Object.entries(options))
		if (typeof fn !== "function")
			throw new ValueError(
				`myuri({ ${name} }) takes the function that replaces the part, got ${pyRepr(fn)}`,
			);
	return { engine: "myuri", options: { ...options } };
}

export const cursory = myuri;

const IN_BROWSER =
	"the browser does not humanize input: each Playwright call is one event. " +
	"Pass True, or myuri() or raw() per channel (camoufox.humanize)";

function asEngine(channel: Channel, value: unknown): Engine {
	const entry = value as Partial<Engine> | null;
	if (
		typeof entry !== "object" ||
		!["myuri", "cursory", "raw"].includes(entry?.engine as string)
	)
		throw new ValueError(
			`humanize["${channel}"]=${pyRepr(value)} is not an engine; ${IN_BROWSER}`,
		);
	const options = entry?.options ?? {};
	if (entry?.engine === "raw") {
		if (Object.keys(options).length)
			throw new ValueError(`humanize["${channel}"]: raw() takes no options`);
		return raw();
	}
	const engine = myuri(options);
	const allowed = CHANNEL_PARTS[channel];
	const misplaced = Object.keys(options)
		.filter((key) => !allowed.includes(key))
		.sort();
	if (misplaced.length)
		throw new ValueError(
			`humanize["${channel}"]: myuri({ ${misplaced[0]} }) is not a ${channel} part; ` +
				`the ${channel} parts are ${allowed.join(", ")}`,
		);
	return engine;
}

/** A checked `humanize` setting. */
export interface Humanize {
	engines: Record<Channel, Engine>;
	seed?: number;
	settings: DeepPartial<MyuriSettings>;
}

/**
 * The engine per channel of a `humanize` setting, the seed if given, and
 * myuri's settings ({} when not given).
 */
export function normalize(humanize: unknown): Humanize {
	const every = (engine: () => Engine) => ({
		engines: Object.fromEntries(CHANNELS.map((c) => [c, engine()])) as Record<
			Channel,
			Engine
		>,
		settings: {},
	});
	if (humanize === null || humanize === undefined || humanize === false)
		return every(raw);
	if (humanize === true) return every(myuri);
	if (typeof humanize !== "object" || Array.isArray(humanize))
		throw new ValueError(`humanize=${pyRepr(humanize)}: ${IN_BROWSER}`);
	const setting = humanize as Record<string, unknown>;
	const unknown = Object.keys(setting).filter(
		(key) =>
			!(CHANNELS as readonly string[]).includes(key) &&
			key !== "seed" &&
			key !== "settings",
	);
	if (unknown.length)
		throw new ValueError(
			`humanize has no channel ${JSON.stringify(unknown)}; the channels are ${CHANNELS.join(", ")}, and "seed" and "settings"`,
		);
	const seed = (setting.seed ?? undefined) as number | undefined;
	if (
		seed !== undefined &&
		(!Number.isInteger(seed) || seed < 0 || seed >= 2 ** 32)
	)
		throw new ValueError(
			`humanize.seed must be an integer in [0, 2**32), got ${String(seed)}`,
		);
	const settings = (setting.settings ?? {}) as DeepPartial<MyuriSettings>;
	if (typeof settings !== "object" || Array.isArray(settings))
		throw new ValueError(
			`humanize.settings must be an object of myuri settings, got ${pyRepr(settings)}`,
		);
	try {
		resolveSettings(settings);
	} catch (e) {
		throw new ValueError(`humanize.settings: ${(e as Error).message}`);
	}
	const engines = Object.fromEntries(
		CHANNELS.map((c) => [
			c,
			asEngine(c, setting[c] === undefined ? myuri() : setting[c]),
		]),
	) as Record<Channel, Engine>;
	return { engines, seed, settings };
}

/** The channels of a `humanize` setting that an engine in this process drives. */
export function drivenChannels(humanize: unknown): Channel[] {
	const { engines } = normalize(humanize);
	return CHANNELS.filter((c) => engines[c].engine !== "raw");
}
