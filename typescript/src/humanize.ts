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
 * A client-side `custom(fn)` engine is Python-only for now: it runs in the
 * caller's process and wraps Playwright's input methods, which this package
 * does not do.
 */

import { PyFloat } from "./pycompat.js";
import { LeakWarning } from "./warnings.js";

export const CHANNELS = ["mouse", "keyboard", "scroll"] as const;
export type Channel = (typeof CHANNELS)[number];

export interface Engine {
	engine: string;
	options: Record<string, number>;
}

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

export function custom(_fn: unknown): Engine {
	throw new Error(
		"custom() humanize engines are Python-only in this package; use raw()/cursory()/auto()/engine() here",
	);
}

function asEngine(channel: string, value: unknown): Engine {
	const candidate = typeof value === "string" ? engine(value) : value;
	if (
		!candidate ||
		typeof candidate !== "object" ||
		typeof (candidate as Engine).engine !== "string"
	)
		throw new Error(
			`humanize["${channel}"] must be an engine such as auto(), raw(), cursory() or engine(name), got ${String(value)}`,
		);
	const entry = candidate as Engine;
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
	const seed = humanize.seed as number | bigint | undefined;
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
		CHANNELS.map((c) => [c, asEngine(c, humanize[c] ?? "auto")]),
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
	const names = Object.fromEntries(
		CHANNELS.map((c) => [c, engines[c].engine]),
	) as Record<Channel, string>;
	for (const channel of CHANNELS) {
		if (
			names[channel] !== "auto" &&
			names[channel] !== "raw" &&
			!(available[channel] ?? []).includes(names[channel])
		)
			throw new Error(
				`humanize:${channel} names "${names[channel]}", which humanize-engines.json does not list for ${channel}`,
			);
	}
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
			throw new Error(
				`humanize:${unsupported} names "${names[unsupported]}"; this build predates per-channel humanize`,
			);
		if (seed !== undefined)
			throw new Error(
				"this build predates per-channel humanize and has no seeded input",
			);
		return enabled ? { humanize: true, ...options } : {};
	}
	// Off adds no keys, so a stock identity mirror has no humanize config.
	if (!enabled) return {};
	const config: Record<string, unknown> = { humanize: enabled };
	for (const channel of CHANNELS)
		config[`humanize:${channel}`] = names[channel];
	Object.assign(config, options);
	if (seed !== undefined) config["humanize:seed"] = String(seed);
	return config;
}
