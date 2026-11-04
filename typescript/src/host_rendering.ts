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
import { GPU_PREFS } from "./gpudisplay.js";

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
	// A key the caller set is kept even when its value is null, as Python's
	// setdefault keeps it.
	if (!("dom.webgpu.enabled" in prefs)) {
		prefs["dom.webgpu.enabled"] =
			targetOs === "win" || (targetOs === "mac" && gpu[0] === "Apple");
	}
	if (prefs["dom.webgpu.enabled"] && !(WEBGPU_BLOCKLIST_PREF in prefs)) {
		const ownAdapter =
			rendersOnHardware(host) && gpu[0] === host[0] && gpu[1] === host[1];
		prefs[WEBGPU_BLOCKLIST_PREF] = ownAdapter
			? FEATURE_STATUS_OK
			: FEATURE_BLOCKED_DEVICE;
	}
}

const probes = new Map<string, Promise<Gpu | null>>();

/** A browser that cannot answer a WebGL probe must not hold the launch forever. */
export const HOST_GPU_PROBE_TIMEOUT_MS = 30_000;
const HOST_GPU_CLOSE_TIMEOUT_MS = 1_000;

function within<T>(
	promise: Promise<T>,
	timeoutMs: number,
	message: string,
): Promise<T> {
	return new Promise<T>((resolve, reject) => {
		const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
		timer.unref();
		promise.then(
			(value) => {
				clearTimeout(timer);
				resolve(value);
			},
			(error) => {
				clearTimeout(timer);
				reject(error);
			},
		);
	});
}

/**
 * The [vendor, renderer] this machine's Firefox reports, or null without WebGL.
 *
 * Read from the binary about to launch, with no identity applied, under the
 * same display and the same rendering prefs: headless, Xvfb, a GPU display and
 * a real display can each render on a different device. The strings are the
 * ones Firefox sanitizes itself.
 */
export function hostGpu(
	executablePath: string,
	headless: boolean,
	env: Record<string, string | number | boolean>,
	prefs: Record<string, any>,
): Promise<Gpu | null> {
	const hostEnv = Object.entries(env)
		.filter(([key]) => !LAUNCHER_ENV.some((prefix) => key.startsWith(prefix)))
		.map(([key, value]) => [key, String(value)])
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
	const hostPrefs = Object.keys(GPU_PREFS)
		.filter((key) => key in prefs)
		.map((key) => [key, prefs[key]]);
	const key = JSON.stringify([executablePath, headless, hostEnv, hostPrefs]);
	let gpu = probes.get(key);
	if (!gpu) {
		gpu = readGpu(
			executablePath,
			headless,
			Object.fromEntries(hostEnv),
			Object.fromEntries(hostPrefs),
		);
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
	prefs: Record<string, any>,
): Promise<Gpu | null> {
	// A display that accepts connections but never answers the X handshake
	// leaves Firefox inside getContext() forever. The launch, the read and the
	// cleanup share one deadline, and a timeout says what it was waiting on.
	const deadline = Date.now() + HOST_GPU_PROBE_TIMEOUT_MS;
	const display = env.DISPLAY ? ` (DISPLAY=${env.DISPLAY})` : "";
	const timeoutMessage =
		`Host GPU probe timed out after ${HOST_GPU_PROBE_TIMEOUT_MS} ms ` +
		`while launching ${executablePath}${display}. The browser did not answer ` +
		"the WebGL probe; check that the display accepts X connections.";
	const remaining = () => Math.max(1, deadline - Date.now());
	let browser: Awaited<ReturnType<typeof firefox.launch>> | undefined;
	let result: Gpu | null = null;
	let failed = false;
	let failure: unknown;
	let closeFailure: unknown;
	try {
		browser = await within(
			firefox.launch({
				executablePath,
				headless,
				env,
				timeout: remaining(),
				// The launch forces WebGL on, which can choose another device.
				firefoxUserPrefs: { ...prefs, "webgl.force-enabled": true },
			}),
			remaining(),
			timeoutMessage,
		);
		const page = await within(browser.newPage(), remaining(), timeoutMessage);
		result = await within(
			page.evaluate((): Gpu | null => {
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
			}),
			remaining(),
			timeoutMessage,
		);
	} catch (error) {
		failed = true;
		failure = error;
	} finally {
		if (browser) {
			try {
				await within(
					browser.close(),
					HOST_GPU_CLOSE_TIMEOUT_MS,
					`Host GPU probe browser.close timed out after ${HOST_GPU_CLOSE_TIMEOUT_MS} ms`,
				);
			} catch (error) {
				closeFailure = error;
			}
		}
	}
	// The read failure is the one to report; a close failure only on its own.
	if (failed) throw failure;
	if (closeFailure !== undefined) throw closeFailure;
	return result;
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
