/**
 * Whole-identity coherence: the checks that look at more than one field.
 *
 * TypeScript twin of pythonlib/camoufox/coherence.py -- see there for the
 * measurements behind each rule. Camoufox assembles an identity from several
 * independently sampled pools, so a combination no machine has ever had can
 * be built out of individually plausible parts; every identity passes through
 * here, whatever it was built from.
 *
 * `validate()` reports what is still broken; `apply()` repairs what it can.
 */
import { isPyInt, num, pyRepr, pyStr, pyTruthy } from "./pycompat.js";

type Config = Record<string, any>;

/** Core counts Apple Silicon actually ships. */
export const APPLE_SILICON_CORES: ReadonlySet<number> = new Set([
	8, 10, 11, 12, 14, 16, 20, 24, 28, 32,
]);

/**
 * devicePixelRatio by platform, ascending as in coherence.py: the
 * nearest-step repair keeps the first of two equally near steps, so a tie
 * goes to the lower one.
 */
export const PLAUSIBLE_DPR: Readonly<Record<string, readonly number[]>> = {
	win: [1, 1.25, 1.5, 1.75, 2, 2.5, 3],
	mac: [1, 2],
	lin: [1, 1.25, 1.5, 1.75, 2],
};

/** colorDepth: Firefox reports 24, or 30 on a deep-colour display. */
export const PLAUSIBLE_COLOR_DEPTH: ReadonlySet<number> = new Set([24, 30]);

/** maxTouchPoints: consumer digitisers top out at 10 contacts. */
export const MAX_PLAUSIBLE_TOUCH_POINTS = 10;

/** The browser's own chrome height, in CSS pixels (a property of the binary). */
export const BROWSER_CHROME_HEIGHT = 86;

/** GPU strings that are not possible on macOS. */
const NOT_A_MAC_GPU = [
	"ANGLE",
	"Intel(R) HD Graphics 400",
	"Radeon R9 200 Series",
	"llvmpipe",
];

export interface Violation {
	rule: string;
	detail: string;
}

export interface Rule {
	name: string;
	/** Returns a description of the breakage, or null when the identity holds. */
	check: (config: Config, targetOs: string) => string | null;
	/** Repairs the identity in place. null where no correct value is determined. */
	repair: ((config: Config, targetOs: string) => void) | null;
}

function isNone(value: unknown): boolean {
	return value === null || value === undefined;
}

function renderer(config: Config): string {
	const r = config["webGl:renderer"];
	return pyTruthy(r) ? pyStr(r) : "";
}

function isAppleSilicon(config: Config): boolean {
	return renderer(config).includes("Apple M");
}

function checkAppleSiliconCores(
	config: Config,
	_targetOs: string,
): string | null {
	if (!isAppleSilicon(config)) return null;
	const cores = config["navigator.hardwareConcurrency"];
	if (isPyInt(cores) && !APPLE_SILICON_CORES.has(Number(cores))) {
		return `${pyRepr(renderer(config))} with hardwareConcurrency ${pyStr(cores)}; Apple Silicon starts at 8`;
	}
	return null;
}

function repairAppleSiliconCores(config: Config, _targetOs: string): void {
	const cores = config["navigator.hardwareConcurrency"];
	if (!isPyInt(cores)) return;
	const n = Number(cores);
	const sorted = [...APPLE_SILICON_CORES].sort((a, b) => a - b);
	config["navigator.hardwareConcurrency"] =
		sorted.find((c) => c >= n) ?? Math.max(...sorted);
}

/**
 * Whether this renderer string is one the OS can report. Used both to check
 * a finished identity and to filter the WebGL pool before sampling.
 */
export function gpuFitsOs(
	rendererString: string | null | undefined,
	targetOs: string,
): boolean {
	const r = pyTruthy(rendererString) ? pyStr(rendererString) : "";
	if (!r) return true;
	if (targetOs === "mac") return !NOT_A_MAC_GPU.some((bad) => r.includes(bad));
	if (targetOs === "win") return r.startsWith("ANGLE");
	if (targetOs === "lin") return !r.includes("ANGLE") && !r.includes("Apple M");
	return true;
}

function checkGpuMatchesOs(config: Config, targetOs: string): string | null {
	const r = renderer(config);
	if (!r || gpuFitsOs(r, targetOs)) return null;
	if (targetOs === "mac")
		return `macOS identity with ${pyRepr(r)}, which no Mac reports`;
	if (targetOs === "win") {
		return `Windows identity with ${pyRepr(r)}; Firefox on Windows renders through ANGLE`;
	}
	return `Linux identity with ${pyRepr(r)}`;
}

function inColorDepths(depth: unknown): boolean {
	return typeof depth !== "boolean" && PLAUSIBLE_COLOR_DEPTH.has(num(depth));
}

function checkColorDepth(config: Config, targetOs: string): string | null {
	const depth = config["screen.colorDepth"];
	if (isNone(depth)) return null;
	if (!inColorDepths(depth))
		return `screen.colorDepth ${pyStr(depth)}; Firefox reports 24 or 30`;
	if (targetOs === "mac" && isAppleSilicon(config) && num(depth) !== 30) {
		return `Apple Silicon Mac with colorDepth ${pyStr(depth)}; deep colour is the macOS default`;
	}
	return null;
}

function repairColorDepth(config: Config, targetOs: string): void {
	const depth = config["screen.colorDepth"];
	if (!isNone(depth) && !inColorDepths(depth)) config["screen.colorDepth"] = 24;
	if (targetOs === "mac" && isAppleSilicon(config))
		config["screen.colorDepth"] = 30;
	// pixelDepth is the same number in every browser that reports both.
	if ("screen.pixelDepth" in config || "screen.colorDepth" in config) {
		config["screen.pixelDepth"] =
			"screen.colorDepth" in config ? config["screen.colorDepth"] : 24;
	}
}

function checkTouchPoints(config: Config, targetOs: string): string | null {
	const touch = config["navigator.maxTouchPoints"];
	if (isNone(touch)) return null;
	if (
		!isPyInt(touch) ||
		Number(touch) < 0 ||
		Number(touch) > MAX_PLAUSIBLE_TOUCH_POINTS
	) {
		return `navigator.maxTouchPoints ${pyStr(touch)}; a digitiser reports at most ${MAX_PLAUSIBLE_TOUCH_POINTS}`;
	}
	if (targetOs === "mac" && pyTruthy(touch)) {
		return `macOS identity with maxTouchPoints ${pyStr(touch)}; no Mac has a touchscreen`;
	}
	return null;
}

function repairTouchPoints(config: Config, targetOs: string): void {
	const touch = config["navigator.maxTouchPoints"];
	const tooMany = isPyInt(touch) && Number(touch) > MAX_PLAUSIBLE_TOUCH_POINTS;
	if (targetOs === "mac" || tooMany || (!isNone(touch) && !isPyInt(touch))) {
		config["navigator.maxTouchPoints"] = 0;
	}
}

function checkDevicePixelRatio(
	config: Config,
	targetOs: string,
): string | null {
	const dpr = config["window.devicePixelRatio"];
	if (isNone(dpr)) return null;
	const allowed = PLAUSIBLE_DPR[targetOs];
	if (allowed?.length && !allowed.includes(Number(num(dpr)))) {
		return `window.devicePixelRatio ${pyStr(dpr)} is not a display mode ${targetOs} offers`;
	}
	return null;
}

function repairDevicePixelRatio(config: Config, targetOs: string): void {
	const dpr = config["window.devicePixelRatio"];
	const allowed = PLAUSIBLE_DPR[targetOs];
	if (isNone(dpr) || !allowed?.length) return;
	// Nearest real scaling step; min() keeps the first of equal distances.
	const x = Number(num(dpr));
	let best = allowed[0];
	for (const v of allowed.slice(1)) {
		if (Math.abs(v - x) < Math.abs(best - x)) best = v;
	}
	config["window.devicePixelRatio"] = best;
}

function checkWindowChrome(config: Config, _targetOs: string): string | null {
	const inner = config["window.innerHeight"];
	const outer = config["window.outerHeight"];
	if (!pyTruthy(inner) || !pyTruthy(outer)) return null;
	const chrome = num(outer) - num(inner);
	if (chrome < BROWSER_CHROME_HEIGHT) {
		return (
			`window.outerHeight ${pyStr(outer)} - innerHeight ${pyStr(inner)} = ${pyStr(chrome)}, less than the ` +
			`${BROWSER_CHROME_HEIGHT}px of chrome the window actually has; the bottom ` +
			`${pyStr(BROWSER_CHROME_HEIGHT - chrome)}px of the claimed viewport cannot receive input`
		);
	}
	return null;
}

function repairWindowChrome(config: Config, _targetOs: string): void {
	const inner = config["window.innerHeight"];
	const outer = config["window.outerHeight"];
	if (!pyTruthy(inner) || !pyTruthy(outer)) return;
	const avail = pyTruthy(config["screen.availHeight"])
		? config["screen.availHeight"]
		: config["screen.height"];
	// Prefer growing the window, which keeps the viewport the identity drew.
	if (!pyTruthy(avail) || num(inner) + BROWSER_CHROME_HEIGHT <= num(avail)) {
		config["window.outerHeight"] = num(inner) + BROWSER_CHROME_HEIGHT;
		return;
	}
	// No room on the claimed screen: shrink the viewport instead.
	config["window.innerHeight"] = Math.max(
		num(outer) - BROWSER_CHROME_HEIGHT,
		1,
	);
}

function checkScreenShape(config: Config, _targetOs: string): string | null {
	const width = config["screen.width"];
	const height = config["screen.height"];
	if (!pyTruthy(width) || !pyTruthy(height)) return null;
	if (num(height) > num(width)) {
		return `portrait screen ${pyStr(width)}x${pyStr(height)}; desktop panels are landscape`;
	}
	if (num(width) < 1024) {
		return `screen ${pyStr(width)}x${pyStr(height)} is smaller than any current desktop panel`;
	}
	return null;
}

function checkAvailBounds(config: Config, _targetOs: string): string | null {
	const width = config["screen.width"];
	const height = config["screen.height"];
	const availW = config["screen.availWidth"];
	const availH = config["screen.availHeight"];
	if (pyTruthy(width) && pyTruthy(availW) && num(availW) > num(width)) {
		return `screen.availWidth ${pyStr(availW)} exceeds screen.width ${pyStr(width)}`;
	}
	if (pyTruthy(height) && pyTruthy(availH) && num(availH) > num(height)) {
		return `screen.availHeight ${pyStr(availH)} exceeds screen.height ${pyStr(height)}`;
	}
	return null;
}

function repairAvailBounds(config: Config, _targetOs: string): void {
	const width = config["screen.width"];
	const height = config["screen.height"];
	const availW =
		"screen.availWidth" in config ? config["screen.availWidth"] : 0;
	const availH =
		"screen.availHeight" in config ? config["screen.availHeight"] : 0;
	if (pyTruthy(width) && num(availW) > num(width))
		config["screen.availWidth"] = width;
	if (pyTruthy(height) && num(availH) > num(height))
		config["screen.availHeight"] = height;
}

function checkArchAgreement(config: Config, _targetOs: string): string | null {
	const str = (key: string) =>
		pyTruthy(config[key]) ? pyStr(config[key]) : "";
	const ua = str("navigator.userAgent");
	const platform = str("navigator.platform");
	const oscpu = str("navigator.oscpu");
	if (!ua) return null;
	if (
		ua.includes("x86_64") &&
		(platform.includes("armv") || oscpu.includes("armv"))
	) {
		return `user agent claims x86_64 while platform/oscpu say ${pyRepr(platform)}/${pyRepr(oscpu)}`;
	}
	return null;
}

export const RULES: readonly Rule[] = [
	{
		name: "apple-silicon-cores",
		check: checkAppleSiliconCores,
		repair: repairAppleSiliconCores,
	},
	{ name: "gpu-matches-os", check: checkGpuMatchesOs, repair: null },
	{ name: "color-depth", check: checkColorDepth, repair: repairColorDepth },
	{ name: "touch-points", check: checkTouchPoints, repair: repairTouchPoints },
	{
		name: "device-pixel-ratio",
		check: checkDevicePixelRatio,
		repair: repairDevicePixelRatio,
	},
	{
		name: "window-chrome",
		check: checkWindowChrome,
		repair: repairWindowChrome,
	},
	{ name: "screen-shape", check: checkScreenShape, repair: null },
	{ name: "avail-bounds", check: checkAvailBounds, repair: repairAvailBounds },
	{ name: "arch-agreement", check: checkArchAgreement, repair: null },
];

/** Whether the screen is one no desktop reports (portrait, or tiny). */
export function screenIsImplausible(config: Config): boolean {
	return checkScreenShape(config, "") !== null;
}

/**
 * Turn a portrait screen landscape, keeping the panel's own dimensions. Run
 * before the window clamps, which then bound the window to the new screen.
 */
export function repairScreenOrientation(config: Config): boolean {
	const width = config["screen.width"];
	const height = config["screen.height"];
	if (!pyTruthy(width) || !pyTruthy(height) || num(height) <= num(width))
		return false;
	config["screen.width"] = height;
	config["screen.height"] = width;
	const availW = config["screen.availWidth"];
	const availH = config["screen.availHeight"];
	if (pyTruthy(availW) && pyTruthy(availH)) {
		config["screen.availWidth"] = availH;
		config["screen.availHeight"] = availW;
	}
	return true;
}

/**
 * Discard values a source supplied that this identity cannot keep (a preset's
 * GPU pair its OS cannot report), so the normal WebGL sampling draws a
 * coherent one instead. Only values another pool can replace are dropped.
 */
export function dropIncoherentSourceValues(
	config: Config,
	targetOs: string,
): Violation[] {
	const dropped: Violation[] = [];
	const r = renderer(config);
	if (r && !gpuFitsOs(r, targetOs)) {
		delete config["webGl:renderer"];
		delete config["webGl:vendor"];
		dropped.push({
			rule: "gpu-matches-os",
			detail: `dropped ${pyRepr(r)} for a ${targetOs} identity`,
		});
	}
	return dropped;
}

/** Every invariant this identity breaks. Empty means coherent. */
export function validate(config: Config, targetOs: string): Violation[] {
	const violations: Violation[] = [];
	for (const rule of RULES) {
		const detail = rule.check(config, targetOs);
		if (detail) violations.push({ rule: rule.name, detail });
	}
	return violations;
}

/**
 * Repair what is determined, and report what is left. A rule with no repair
 * cannot be corrected without inventing a machine, so it is returned for the
 * caller to decide about.
 */
export function apply(config: Config, targetOs: string): Violation[] {
	for (const rule of RULES) {
		if (rule.repair && rule.check(config, targetOs))
			rule.repair(config, targetOs);
	}
	return validate(config, targetOs);
}
