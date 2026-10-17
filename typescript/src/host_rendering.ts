/**
 * What this machine renders, and covering it when the identity claims another
 * machine. The twin of host_rendering.py.
 *
 * A page can draw a canvas or a WebGL scene and read the pixels back, and those
 * pixels come from the real OS, driver and GPU whatever the identity claims. On
 * the host's own OS the identity claims the GPU the host renders with, so the
 * pixels agree with it. An identity on another OS, or naming another GPU,
 * cannot agree, so its canvas readback is replaced with random data, as
 * privacy.resistFingerprinting does in LibreWolf, Tor Browser and Mullvad
 * Browser. Stock Firefox does not do that.
 * WebGPU hands the page the host's adapter, so the identity gets it only when it
 * claims the host's GPU.
 */
import { firefox } from "playwright-core";
import { isSoftwareRenderer } from "./fingerprints.js";

export const BASELINE_OVERRIDES_PREF =
	"privacy.baselineFingerprintingProtection.overrides";

// The canvas targets privacy.resistFingerprinting turns on, and only those:
// readback without the site's permission returns random data.
export const CANVAS_PLACEHOLDER_TARGETS = [
	"+CanvasImageExtractionPrompt",
	"+CanvasExtractionBeforeUserInputIsBlocked",
	"+CanvasExtractionFromThirdPartiesIsBlocked",
] as const;

// The downloadable blocklist's pref for WebGPU and its nsIGfxInfo statuses
// (widget/GfxInfoFeatureStatusDefs.inc). A blocked device resolves
// requestAdapter() to null, as on a machine whose GPU Firefox blocks.
export const WEBGPU_BLOCKLIST_PREF = "gfx.blacklist.webgpu";
export const FEATURE_STATUS_OK = 1;
export const FEATURE_BLOCKED_DEVICE = 4;

// Firefox reports the renderer through SanitizeRenderer.cpp, which keeps a
// vendor only for strings it recognises: Mesa's d3d12 driver under WSL says
// "D3D12 (NVIDIA GeForce RTX 4090)", and Firefox reports "Generic Renderer"
// for it. With the pref off it reports the driver's own string.
export const SANITIZE_RENDERER_PREF = "webgl.sanitize-unmasked-renderer";

// The GPU vendors a renderer or vendor string can name, as Firefox reports them
// on each OS ("ANGLE (NVIDIA, ...)", "GeForce GTX 980, or similar", "Intel
// Inc.", "ATI Technologies Inc.") and as drivers do ("D3D12 (AMD Radeon RX
// 6800)", "Mesa Intel(R) UHD Graphics 620 (KBL GT2)").
const GPU_FAMILIES: Array<[string, RegExp]> = [
	["NVIDIA", /NVIDIA|GeForce|Quadro|nouveau/],
	["AMD", /\bAMD\b|\bATI\b|Radeon|FirePro|Advanced Micro Devices/],
	["Intel", /Intel/],
	["Apple", /\bApple\b/],
];

// What the launcher itself adds to the browser's environment; none of it
// changes which device Firefox renders on.
const LAUNCHER_ENV = ["CAMOU_", "FONTCONFIG_FILE"];

/** A GPU as WEBGL_debug_renderer_info reports it: [vendor, renderer]. */
export type Gpu = [string, string];

/** Turn on the canvas placeholder, keeping any baseline overrides already set. */
export function addCanvasPlaceholder(prefs: Record<string, any>): void {
	const overrides = String(prefs[BASELINE_OVERRIDES_PREF] || "")
		.split(",")
		.filter(Boolean);
	prefs[BASELINE_OVERRIDES_PREF] = [
		...overrides,
		...CANVAS_PLACEHOLDER_TARGETS,
	].join(",");
}

export function hasCanvasPlaceholder(prefs: Record<string, any>): boolean {
	return String(prefs[BASELINE_OVERRIDES_PREF] || "").includes(
		CANVAS_PLACEHOLDER_TARGETS[0],
	);
}

/**
 * Expose navigator.gpu where Firefox on the claimed device has it, with the
 * host's adapter only when `gpu` is the host's hardware GPU, or when the
 * launch passes the host's GPU through (gpu_passthrough).
 *
 * Firefox enables WebGPU on Windows and on Apple Silicon Macs only
 * (dom.webgpu.enabled in StaticPrefList.yaml). Any other adapter would
 * contradict the claimed GPU, so requestAdapter() returns null, as Windows
 * Firefox does on the Microsoft Basic Render Driver. The status is written
 * either way, because a persistent profile saves it and the next startup
 * reads it. Prefs the caller set are kept.
 */
export function setWebgpu(
	prefs: Record<string, any>,
	targetOs: string,
	gpu: [string | undefined, string | undefined],
	host: Gpu | null,
	passthrough = false,
): void {
	// A key the caller set is kept even when its value is null, as Python's
	// setdefault keeps it.
	if (!("dom.webgpu.enabled" in prefs)) {
		prefs["dom.webgpu.enabled"] =
			targetOs === "win" || (targetOs === "mac" && gpu[0] === "Apple");
	}
	if (prefs["dom.webgpu.enabled"] && !(WEBGPU_BLOCKLIST_PREF in prefs)) {
		const ownAdapter =
			passthrough ||
			(rendersOnHardware(host) && gpu[0] === host[0] && gpu[1] === host[1]);
		prefs[WEBGPU_BLOCKLIST_PREF] = ownAdapter
			? FEATURE_STATUS_OK
			: FEATURE_BLOCKED_DEVICE;
	}
}

const probes = new Map<string, Promise<Gpu | null>>();

/**
 * The [vendor, renderer] this machine's Firefox reports, or null without WebGL.
 *
 * Read from the binary about to launch, with no identity applied, under the
 * same display: headless, Xvfb and a real display can each render on a
 * different device. The strings are the ones Firefox sanitizes itself, or
 * with `raw` the driver's own renderer string (SANITIZE_RENDERER_PREF).
 */
export function hostGpu(
	executablePath: string,
	headless: boolean,
	env: Record<string, string | number | boolean>,
	raw = false,
): Promise<Gpu | null> {
	const hostEnv = Object.entries(env)
		.filter(([key]) => !LAUNCHER_ENV.some((prefix) => key.startsWith(prefix)))
		.map(([key, value]) => [key, String(value)])
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
	const key = JSON.stringify([executablePath, headless, hostEnv, raw]);
	let gpu = probes.get(key);
	if (!gpu) {
		gpu = readGpu(executablePath, headless, Object.fromEntries(hostEnv), raw);
		// Remember a reading, not a failure: the next launch tries again.
		gpu.catch(() => probes.delete(key));
		probes.set(key, gpu);
	}
	return gpu;
}

async function readGpu(
	executablePath: string,
	headless: boolean,
	env: Record<string, string>,
	raw: boolean,
): Promise<Gpu | null> {
	const firefoxUserPrefs: Record<string, boolean> = {
		"webgl.force-enabled": true,
	};
	if (raw) firefoxUserPrefs[SANITIZE_RENDERER_PREF] = false;
	const browser = await firefox.launch({
		executablePath,
		headless,
		env,
		// The launch forces WebGL on, which can choose another device.
		firefoxUserPrefs,
	});
	try {
		const page = await browser.newPage();
		return await page.evaluate((): Gpu | null => {
			const gl = (globalThis as any).document
				.createElement("canvas")
				.getContext("webgl");
			const info = gl?.getExtension("WEBGL_debug_renderer_info");
			return info
				? [
						gl.getParameter(info.UNMASKED_VENDOR_WEBGL),
						gl.getParameter(info.UNMASKED_RENDERER_WEBGL),
					]
				: null;
		});
	} finally {
		await browser.close();
	}
}

/**
 * Whether the host's canvas and WebGL come from a GPU, not a software
 * rasterizer.
 *
 * A host that renders in software matches any GPU on its own OS: it reads as a
 * machine whose driver failed to load.
 */
export function rendersOnHardware(gpu: Gpu | null): gpu is Gpu {
	return gpu !== null && !isSoftwareRenderer(gpu[1]);
}

/**
 * The vendor that made `gpu` (NVIDIA, AMD, Intel or Apple), or null.
 *
 * The renderer names the device and is read first: Linux Firefox can report an
 * NVIDIA or AMD GPU under the "Mesa" vendor, and Mesa's d3d12 driver reports
 * every GPU under "Microsoft Corporation". The first vendor the renderer names
 * wins, as in "ANGLE (Intel, Intel(R) HD Graphics ...)".
 */
export function gpuFamily(
	gpu: [string | null | undefined, string | null | undefined],
): string | null {
	for (const text of [gpu[1], gpu[0]]) {
		let first: [number, string] | null = null;
		for (const [family, pattern] of GPU_FAMILIES) {
			const match = pattern.exec(text ?? "");
			if (match && (!first || match.index < first[0])) {
				first = [match.index, family];
			}
		}
		if (first) return first[1];
	}
	return null;
}
