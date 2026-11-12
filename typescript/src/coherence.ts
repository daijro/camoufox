/**
 * Whole-identity coherence: the checks that look at more than one field.
 *
 * TypeScript twin of python/src/camoufox/coherence.py -- see there for the
 * measurements behind each rule. Camoufox assembles an identity from several
 * independently sampled pools, so a combination no machine has ever had can
 * be built out of individually plausible parts; every identity passes through
 * here, whatever it was built from.
 *
 * `validate()` reports what is still broken; `apply()` repairs what it can.
 */
import { LAUNCHER_CONSTANTS } from "./paths.js";
import {
	comparePyStr,
	isPlainObject,
	isPyInt,
	num,
	pyRepr,
	pyStr,
	pyTruthy,
	ValueError,
} from "./pycompat.js";

type Config = Record<string, any>;

/** Core counts Apple Silicon actually ships. */
export const APPLE_SILICON_CORES: ReadonlySet<number> = new Set(
	LAUNCHER_CONSTANTS.appleSiliconCores,
);

/**
 * devicePixelRatio by platform, ascending as in coherence.py: the
 * nearest-step repair keeps the first of two equally near steps, so a tie
 * goes to the lower one.
 */
export const PLAUSIBLE_DPR: Readonly<Record<string, readonly number[]>> =
	LAUNCHER_CONSTANTS.plausibleDpr;

/**
 * colorDepth: Firefox reports 24, or 30 on a deep-colour display. macOS
 * defaults to deep colour, so a Mac reports 30, Intel or Apple Silicon.
 */
export const PLAUSIBLE_COLOR_DEPTH: ReadonlySet<number> = new Set([24, 30]);

/** maxTouchPoints: consumer digitisers top out at 10 contacts. */
export const MAX_PLAUSIBLE_TOUCH_POINTS = 10;

/** The browser's own chrome height, in CSS pixels (a property of the binary). */
export const BROWSER_CHROME_HEIGHT = 86;

/**
 * GPU strings that are not possible on macOS: Firefox 152 has no ANGLE on a
 * Mac. "Intel(R) HD Graphics 400" and "Radeon R9 200 Series" are the buckets
 * an Intel Mac's UHD 630 and Radeon Pro 5300M report.
 */
const NOT_A_MAC_GPU = ["ANGLE", "llvmpipe"];

/** navigator.hardwareConcurrency on an Intel Mac, physical or logical. */
export const INTEL_MAC_IGP_CORES: ReadonlySet<number> = new Set(
	LAUNCHER_CONSTANTS.intelMacIgpCores,
);
/** A discrete GPU adds the desktops to those, up to the 2019 Mac Pro. */
export const INTEL_MAC_DGPU_CORES: ReadonlySet<number> = new Set([
	...LAUNCHER_CONSTANTS.intelMacIgpCores,
	...LAUNCHER_CONSTANTS.intelMacDgpuExtraCores,
]);

/** Screens only Apple Silicon Macs have: the notched MacBooks, the 24" iMac. */
export const APPLE_SILICON_PANELS: ReadonlySet<string> = new Set(
	Object.values(LAUNCHER_CONSTANTS.appleSiliconPanels).flatMap((panels) =>
		panels.map(([w, h]) => `${w}x${h}`),
	),
);

export interface Violation {
	rule: string;
	detail: string;
	/**
	 * The caller's own keys that the repair would have changed, and which were
	 * kept as passed instead. Absent when nothing of the caller's is involved.
	 */
	kept?: string[];
}

export interface Rule {
	name: string;
	/** Returns a description of the breakage, or null when the identity holds. */
	check: (config: Config, targetOs: string) => string | null;
	/** Repairs the identity in place. null where no correct value is determined. */
	repair: ((config: Config, targetOs: string) => void) | null;
	/**
	 * Keys the repair only adjusts to stay consistent with what it repairs. A
	 * caller who set any of them keeps all of them as they were, the repair
	 * itself still runs, and they never block it.
	 */
	adjusts?: readonly string[];
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

function isAppleSiliconPanel(width: unknown, height: unknown): boolean {
	const w = num(width);
	const h = num(height);
	return (
		typeof w === "number" &&
		typeof h === "number" &&
		APPLE_SILICON_PANELS.has(`${w}x${h}`)
	);
}

/** Why no Intel Mac reports this GPU beside these cores and this screen. */
function intelMacMisfit(
	rendererString: unknown,
	cores: unknown,
	width: unknown,
	height: unknown,
): string | null {
	const r = pyTruthy(rendererString) ? pyStr(rendererString) : "";
	if (!r || r.includes("Apple M")) return null;
	const allowed = r.includes("Intel")
		? INTEL_MAC_IGP_CORES
		: INTEL_MAC_DGPU_CORES;
	if (isPyInt(cores) && !allowed.has(Number(cores))) {
		return `${pyRepr(r)} with hardwareConcurrency ${pyStr(cores)}; no Intel Mac with that GPU reports it`;
	}
	if (isAppleSiliconPanel(width, height)) {
		return `${pyRepr(r)} behind a ${pyStr(width)}x${pyStr(height)} panel, which only Apple Silicon Macs have`;
	}
	return null;
}

/**
 * Whether a machine with this GPU has these cores and this screen. Only Intel
 * Macs are modelled; serves the WebGL draw and the finished-identity check.
 */
export function gpuFitsMachine(
	rendererString: string | null | undefined,
	targetOs: string,
	cores?: unknown,
	width?: unknown,
	height?: unknown,
): boolean {
	return (
		targetOs !== "mac" ||
		intelMacMisfit(rendererString, cores, width, height) === null
	);
}

function checkIntelMacHardware(
	config: Config,
	targetOs: string,
): string | null {
	if (targetOs !== "mac") return null;
	return intelMacMisfit(
		renderer(config),
		config["navigator.hardwareConcurrency"],
		config["screen.width"],
		config["screen.height"],
	);
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
	if (targetOs === "mac" && num(depth) !== 30) {
		return `macOS identity with colorDepth ${pyStr(depth)}; deep colour is the macOS default`;
	}
	return null;
}

function repairColorDepth(config: Config, targetOs: string): void {
	if (targetOs === "mac") config["screen.colorDepth"] = 30;
	else if (!inColorDepths(config["screen.colorDepth"]))
		config["screen.colorDepth"] = 24;
	if (!("screen.pixelDepth" in config))
		config["screen.pixelDepth"] = config["screen.colorDepth"];
}

function checkPixelDepth(config: Config, _targetOs: string): string | null {
	// pixelDepth is the same number in every browser that reports both.
	const pixel = config["screen.pixelDepth"];
	const color = config["screen.colorDepth"] ?? 24;
	if (!isNone(pixel) && num(pixel) !== num(color))
		return `screen.pixelDepth ${pyStr(pixel)} differs from colorDepth ${pyStr(color)}`;
	return null;
}

function repairPixelDepth(config: Config, _targetOs: string): void {
	config["screen.pixelDepth"] = config["screen.colorDepth"] ?? 24;
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

// The CSS geometry a ratio scales: device pixels / devicePixelRatio.
const CSS_GEOMETRY_KEYS = [
	"screen.width",
	"screen.height",
	"screen.availWidth",
	"screen.availHeight",
	"screen.availLeft",
	"screen.availTop",
	"window.outerWidth",
	"window.outerHeight",
	"window.innerWidth",
	"window.innerHeight",
	"window.screenX",
	"window.screenY",
] as const;

/** Python's round(): half to even, so both launchers draw the same geometry. */
function roundHalfEven(v: number): number {
	const r = Math.round(v);
	return Math.abs(v % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

/**
 * A devicePixelRatio no display mode of the OS offers: a browser zoom folded
 * into the ratio, which scaled every CSS size with it.
 */
export function isZoomedRatio(dpr: unknown, targetOs: string): boolean {
	const allowed = PLAUSIBLE_DPR[targetOs];
	if (!allowed?.length || typeof dpr !== "number" || !(dpr > 0)) return false;
	return !allowed.some((v) => v === dpr);
}

/**
 * Move the ratio to the nearest display mode, rescaling the CSS geometry so
 * the screen stays the display behind it.
 */
export function repairDevicePixelRatio(
	config: Config,
	targetOs: string,
	target?: number,
): void {
	const dpr = config["window.devicePixelRatio"];
	const allowed = PLAUSIBLE_DPR[targetOs];
	if (isNone(dpr) || !allowed?.length) return;
	// `target` is the scale a caller renders at; else the nearest real scaling
	// step (min() keeps the first of equal distances).
	const x = Number(num(dpr));
	let best = allowed[0];
	for (const v of allowed.slice(1)) {
		if (Math.abs(v - x) < Math.abs(best - x)) best = v;
	}
	if (target !== undefined && target > 0) best = target;
	config["window.devicePixelRatio"] = best;
	// The scraped ratio has a browser zoom folded in, which shrank every CSS
	// size by it; the display behind it keeps its device pixels. Rescale to the
	// step so the screen is still that display: 1760x990 at 1.0909 is a
	// 1920x1080 monitor, so 1920x1080 at 1. Firefox rounds device / ratio.
	const scale = x / best;
	for (const key of CSS_GEOMETRY_KEYS) {
		const value = config[key];
		if (typeof value === "number") {
			config[key] = roundHalfEven(value * scale);
		}
	}
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

// The CPU the identity claims: its architecture (cpu:arch) and manufacturer
// (cpu:manufacturer); coherence.py explains why it shows (canvas, Web Audio,
// Opus, relaxed-SIMD wasm and NaN signs differ between x86-64 and ARM64, and
// canvas and Opus between Intel and AMD) and has the sources for the table of
// manufacturers per OS (launcher-constants.json, cpuManufacturers).
//
// The GPU decides where it can: Intel integrated graphics, Intel; "Radeon HD
// 3200 Graphics", the bucket of AMD's APU graphics, AMD; every x86 Mac, Intel;
// an Apple GPU, Apple ARM; an Adreno, Qualcomm; a VideoCore/V3D, Broadcom; a
// Mali, an ARM SoC of some other maker. Any other GPU leaves the CPU open. A
// core count only Intel's hybrids report (10, 14, 18, 22, 28) implies Intel,
// for x86 only (an M4 Pro has 14).
export const CPU_ARCHES = ["x86", "arm"] as const;
export type CpuArch = (typeof CPU_ARCHES)[number];
export const CPU_MANUFACTURERS: Readonly<
	Record<string, Readonly<Record<string, readonly string[]>>>
> = LAUNCHER_CONSTANTS.cpuManufacturers;
export const CPU_VENDORS = ["intel", "amd"] as const;
const INTEL_ONLY_CORE_COUNTS: ReadonlySet<unknown> = new Set(
	LAUNCHER_CONSTANTS.intelOnlyCoreCounts,
);
export type CpuVendor = (typeof CPU_VENDORS)[number];
const INTEL_IGPUS = [
	"Intel(R) HD Graphics, or similar",
	"Intel(R) HD Graphics 400, or similar",
	"Intel(R) HD Graphics Direct3D11",
	"Intel(R) HD Graphics 400 Direct3D11",
];
const AMD_IGPUS = ["Radeon HD 3200 Graphics"];
/** ARM GPUs and the SoC makers that ship them. */
const ARM_GPUS: ReadonlyArray<[string, readonly string[]]> = [
	["Apple M", ["apple"]],
	["Apple GPU", ["apple"]],
	["Adreno", ["qualcomm"]],
	["V3D", ["broadcom"]],
	["VideoCore", ["broadcom"]],
	["Mali", ["rockchip", "mediatek", "amlogic", "allwinner"]],
	["Immortalis", ["mediatek"]],
	["Tegra", ["nvidia"]],
];

/** The cpuManufacturers key for a launcher OS name (win, mac, lin, ...). */
export function cpuOs(targetOs: string): "windows" | "mac" | "linux" {
	const map: Record<string, "windows" | "mac"> = {
		win: "windows",
		windows: "windows",
		mac: "mac",
		macos: "mac",
	};
	return Object.hasOwn(map, targetOs) ? map[targetOs] : "linux";
}

export function cpuManufacturers(
	targetOs: string,
	arch: unknown,
): readonly string[] {
	const table = CPU_MANUFACTURERS[cpuOs(targetOs)];
	return typeof arch === "string" && Object.hasOwn(table, arch)
		? table[arch]
		: [];
}

/**
 * Check a caller's `cpu` option and fill in what it implies, as
 * coherence.resolve_cpu does. Throws ValueError for anything no real machine
 * running `targetOs` is: an unknown key, architecture or manufacturer, or a
 * pair such as an AMD Mac or an Apple x86 CPU. A manufacturer alone implies
 * its architecture.
 */
export function resolveCpu(
	cpu: unknown,
	targetOs: string,
): Record<string, string> {
	if (!isPlainObject(cpu)) {
		throw new ValueError(
			`cpu must be a dict such as {'arch': 'x86', 'manufacturer': 'intel'}, not ${pyRepr(cpu)}`,
		);
	}
	const unknownKeys = Object.keys(cpu)
		.filter((k) => k !== "arch" && k !== "manufacturer")
		.sort(comparePyStr);
	if (unknownKeys.length) {
		throw new ValueError(
			`cpu takes 'arch' and 'manufacturer', not ${unknownKeys.map(pyRepr).join(", ")}`,
		);
	}
	let arch: unknown = isNone(cpu.arch) ? null : cpu.arch;
	const maker: unknown = isNone(cpu.manufacturer) ? null : cpu.manufacturer;
	if (arch !== null && !(CPU_ARCHES as readonly unknown[]).includes(arch)) {
		throw new ValueError(
			`cpu arch must be one of ('x86', 'arm'), not ${pyRepr(arch)}`,
		);
	}
	const osName = cpuOs(targetOs);
	const table = CPU_MANUFACTURERS[osName];
	const makersOf = (a: string): readonly string[] =>
		Object.hasOwn(table, a) ? table[a] : [];
	if (maker !== null) {
		const arches = CPU_ARCHES.filter((a) =>
			(makersOf(a) as readonly unknown[]).includes(maker),
		);
		if (!arches.length) {
			const known = [...new Set(Object.values(table).flat())].sort(
				comparePyStr,
			);
			throw new ValueError(
				`no ${osName} machine has a CPU made by ${pyRepr(maker)}; on ${osName} it is one of ${known.join(", ")}`,
			);
		}
		if (arch === null) arch = arches[0];
		else if (!(arches as readonly unknown[]).includes(arch)) {
			throw new ValueError(
				`no ${osName} machine has an ${pyStr(arch)} CPU made by ${pyRepr(maker)}; ${osName} ${pyStr(arch)} CPUs are made by ` +
					`${makersOf(arch as string).join(", ") || "nobody"}`,
			);
		}
	} else if (arch !== null && !makersOf(arch as string).length) {
		throw new ValueError(`no ${osName} machine has an ${pyStr(arch)} CPU`);
	}
	const out: Record<string, string> = {};
	if (arch !== null) out["cpu:arch"] = arch as string;
	if (maker !== null) out["cpu:manufacturer"] = maker as string;
	return out;
}

/**
 * The CPU architecture this GPU implies and the manufacturers it allows, as
 * coherence.gpu_cpu. [null, []] when the GPU leaves both open. An empty list
 * with an architecture means any maker of that architecture on `targetOs`.
 */
export function gpuCpu(
	gpuRenderer: unknown,
	targetOs: string,
): [CpuArch | null, readonly string[]] {
	const r = pyTruthy(gpuRenderer) ? pyStr(gpuRenderer) : "";
	if (!r) return [null, []];
	for (const [marker, makers] of ARM_GPUS) {
		if (r.includes(marker)) return ["arm", makers];
	}
	if (cpuOs(targetOs) === "mac") return ["x86", ["intel"]];
	if (INTEL_IGPUS.some((igpu) => r.includes(igpu))) return ["x86", ["intel"]];
	if (AMD_IGPUS.some((igpu) => r.includes(igpu))) return ["x86", ["amd"]];
	return [null, []];
}

/** Whether a machine with this GPU can have this CPU. */
export function gpuFitsCpu(
	gpuRenderer: unknown,
	targetOs: string,
	arch: unknown,
	maker: unknown,
): boolean {
	const [byGpu, makers] = gpuCpu(gpuRenderer, targetOs);
	let a: unknown = isNone(arch) ? null : arch;
	const m: unknown = isNone(maker) ? null : maker;
	if (a === null && m !== null) {
		a =
			CPU_ARCHES.find((x) =>
				(cpuManufacturers(targetOs, x) as readonly unknown[]).includes(m),
			) ?? null;
	}
	// Mesa's software renderer draws on whatever CPU the machine has.
	if (a === null || pyStr(gpuRenderer ?? "").includes("llvmpipe")) return true;
	if (byGpu === null) {
		// A discrete card or an open bucket: an x86 machine. No ARM laptop or
		// board on sale carries a discrete GPU Firefox would name.
		return a === "x86" && cpuOs(targetOs) !== "mac";
	}
	if (byGpu !== a) return false;
	return (
		m === null || !makers.length || (makers as readonly unknown[]).includes(m)
	);
}

/** The x86 CPU vendor this GPU implies, or null when it leaves it open. */
export function gpuCpuVendor(
	gpuRenderer: unknown,
	targetOs: string,
): CpuVendor | null {
	const [arch, makers] = gpuCpu(gpuRenderer, targetOs);
	return arch === "x86" && makers.length === 1
		? (makers[0] as CpuVendor)
		: null;
}

/** The x86 CPU vendor this navigator.hardwareConcurrency implies, or null. */
export function coresCpuVendor(cores: unknown): CpuVendor | null {
	return INTEL_ONLY_CORE_COUNTS.has(cores) ? "intel" : null;
}

/**
 * The [arch, manufacturer] the identity's GPU or, failing that, its core
 * count implies.
 */
export function hardwareCpu(
	config: Config,
	targetOs: string,
): [CpuArch | null, string | null] {
	const [arch, makers] = gpuCpu(renderer(config), targetOs);
	if (arch === "arm") return [arch, makers.length === 1 ? makers[0] : null];
	const vendor =
		(makers.length ? makers[0] : null) ||
		coresCpuVendor(config["navigator.hardwareConcurrency"]);
	return [vendor || arch ? "x86" : null, vendor];
}

/** The x86 CPU vendor the identity's GPU or, failing that, its core count implies. */
export function hardwareCpuVendor(
	config: Config,
	targetOs: string,
): CpuVendor | null {
	const [arch, maker] = hardwareCpu(config, targetOs);
	return arch === "x86" ? (maker as CpuVendor | null) : null;
}

/** Why the claimed CPU cannot sit in this machine, or null. */
export function cpuConflict(config: Config, targetOs: string): string | null {
	const arch = isNone(config["cpu:arch"]) ? null : config["cpu:arch"];
	const maker = isNone(config["cpu:manufacturer"])
		? null
		: config["cpu:manufacturer"];
	if (arch === null && maker === null) return null;
	const cpu: Record<string, unknown> = {};
	if (arch !== null) cpu.arch = arch;
	if (maker !== null) cpu.manufacturer = maker;
	try {
		resolveCpu(cpu, targetOs);
	} catch (e) {
		if (e instanceof ValueError) return e.message;
		throw e;
	}
	const r = renderer(config);
	const claimed = [maker, arch]
		.filter((v) => pyTruthy(v))
		.map(pyStr)
		.join(" ");
	if (r && !gpuFitsCpu(r, targetOs, arch, maker)) {
		return `CPU ${claimed} beside ${pyRepr(r)}`;
	}
	const cores = config["navigator.hardwareConcurrency"];
	const byCores = coresCpuVendor(cores);
	if (
		(pyTruthy(arch) ? arch : "x86") === "x86" &&
		pyTruthy(maker) &&
		maker !== byCores &&
		byCores
	) {
		return `CPU ${claimed} with hardwareConcurrency ${pyStr(cores)}, which only an Intel CPU reports`;
	}
	return null;
}

function checkCpu(config: Config, targetOs: string): string | null {
	return cpuConflict(config, targetOs);
}

function repairCpu(config: Config, targetOs: string): void {
	// The GPU decides. An AMD APU's GPU beside an Intel-only core count stays
	// reported: no vendor matches both.
	const [implied, maker] = hardwareCpu(config, targetOs);
	const arch = implied ?? "x86";
	config["cpu:arch"] = arch;
	if (maker) config["cpu:manufacturer"] = maker;
	else if (
		!(cpuManufacturers(targetOs, arch) as readonly unknown[]).includes(
			config["cpu:manufacturer"],
		) ||
		cpuConflict(config, targetOs)
	) {
		delete config["cpu:manufacturer"];
	}
}

export const RULES: readonly Rule[] = [
	{
		name: "apple-silicon-cores",
		check: checkAppleSiliconCores,
		repair: repairAppleSiliconCores,
	},
	{ name: "gpu-matches-os", check: checkGpuMatchesOs, repair: null },
	{ name: "intel-mac-hardware", check: checkIntelMacHardware, repair: null },
	{ name: "color-depth", check: checkColorDepth, repair: repairColorDepth },
	{ name: "pixel-depth", check: checkPixelDepth, repair: repairPixelDepth },
	{ name: "touch-points", check: checkTouchPoints, repair: repairTouchPoints },
	{
		name: "device-pixel-ratio",
		check: checkDevicePixelRatio,
		repair: repairDevicePixelRatio,
		adjusts: CSS_GEOMETRY_KEYS,
	},
	{
		name: "window-chrome",
		check: checkWindowChrome,
		repair: repairWindowChrome,
	},
	{ name: "screen-shape", check: checkScreenShape, repair: null },
	{ name: "avail-bounds", check: checkAvailBounds, repair: repairAvailBounds },
	{ name: "arch-agreement", check: checkArchAgreement, repair: null },
	{ name: "cpu-matches-hardware", check: checkCpu, repair: repairCpu },
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

function changed(
	before: Config,
	after: Config,
	keys: ReadonlySet<string>,
): string[] {
	return [...keys]
		.filter(
			(k) =>
				k in before !== k in after ||
				JSON.stringify(before[k]) !== JSON.stringify(after[k]),
		)
		.sort();
}

/**
 * Discard values a source supplied that this identity cannot keep (a preset's
 * GPU pair its OS, or its final core count and screen, rule out), so the
 * normal WebGL sampling draws a coherent one instead. Run after the core count
 * and the screen are final. Only values another pool can replace are dropped.
 * A GPU the caller passed (a key in `keep`) is never dropped: it is reported,
 * with the keys it kept, instead.
 */
export function dropIncoherentSourceValues(
	config: Config,
	targetOs: string,
	keep: ReadonlySet<string> = new Set(),
): Violation[] {
	const r = renderer(config);
	if (!r) return [];
	let rule: string;
	if (!gpuFitsOs(r, targetOs)) rule = "gpu-matches-os";
	else if (checkIntelMacHardware(config, targetOs)) rule = "intel-mac-hardware";
	else return [];
	const kept = changed(
		config,
		{},
		new Set(["webGl:renderer", "webGl:vendor"].filter((k) => keep.has(k))),
	);
	if (kept.length) {
		return [
			{
				rule,
				detail: `${pyRepr(r)} does not fit this ${targetOs} identity`,
				kept,
			},
		];
	}
	delete config["webGl:renderer"];
	delete config["webGl:vendor"];
	return [{ rule, detail: `dropped ${pyRepr(r)} for a ${targetOs} identity` }];
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
 *
 * `keep` names the keys the caller set. A repair that would change one of
 * them is not made: the caller's value stands, and the violation comes back
 * with those keys in `kept` so the launcher can warn about it (#956). A repair
 * that only touches other keys still runs.
 */
export function apply(
	config: Config,
	targetOs: string,
	keep: ReadonlySet<string> = new Set(),
): Violation[] {
	const kept = new Map<string, string[]>();
	for (const rule of RULES) {
		if (!rule.repair || !rule.check(config, targetOs)) continue;
		const repaired: Config = { ...config };
		rule.repair(repaired, targetOs);
		if (rule.adjusts?.some((key) => keep.has(key))) {
			for (const key of rule.adjusts) {
				if (key in config) repaired[key] = config[key];
				else delete repaired[key];
			}
		}
		const blocked = changed(config, repaired, keep);
		if (blocked.length) {
			kept.set(rule.name, blocked);
		} else {
			for (const key of Object.keys(config))
				if (!(key in repaired)) delete config[key];
			Object.assign(config, repaired);
		}
	}
	return validate(config, targetOs).map((v) =>
		kept.has(v.rule) ? { ...v, kept: kept.get(v.rule) } : v,
	);
}
