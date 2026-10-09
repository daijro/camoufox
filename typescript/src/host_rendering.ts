/**
 * What this machine renders, and covering it when the identity claims another
 * OS. The twin of host_rendering.py.
 *
 * A page can draw a canvas or a WebGL scene and read the pixels back, and those
 * pixels come from the real OS, driver and GPU whatever the identity claims. On
 * the host's own OS the identity claims the GPU the host renders with, so the
 * pixels agree with it. An identity on another OS cannot agree, so its canvas
 * readback is replaced with random data, as privacy.resistFingerprinting does
 * in LibreWolf, Tor Browser and Mullvad Browser. Stock Firefox does not do that.
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
 * host's adapter only when `gpu` is the host's hardware GPU.
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
): void {
	prefs["dom.webgpu.enabled"] ??=
		targetOs === "win" || (targetOs === "mac" && gpu[0] === "Apple");
	if (prefs["dom.webgpu.enabled"]) {
		const ownAdapter =
			rendersOnHardware(host) && gpu[0] === host[0] && gpu[1] === host[1];
		prefs[WEBGPU_BLOCKLIST_PREF] ??= ownAdapter
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
 * different device. The strings are the ones Firefox sanitizes itself.
 */
export function hostGpu(
	executablePath: string,
	headless: boolean,
	env: Record<string, string | number | boolean>,
): Promise<Gpu | null> {
	const hostEnv = Object.entries(env)
		.filter(([key]) => !LAUNCHER_ENV.some((prefix) => key.startsWith(prefix)))
		.map(([key, value]) => [key, String(value)])
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
	const key = JSON.stringify([executablePath, headless, hostEnv]);
	let gpu = probes.get(key);
	if (!gpu) {
		gpu = readGpu(executablePath, headless, Object.fromEntries(hostEnv));
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
): Promise<Gpu | null> {
	const browser = await firefox.launch({
		executablePath,
		headless,
		env,
		// The launch forces WebGL on, which can choose another device.
		firefoxUserPrefs: { "webgl.force-enabled": true },
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
