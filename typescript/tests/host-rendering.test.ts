/**
 * The canvas renders on the host: an identity on the host's OS claims the
 * host's GPU, and one on another OS gets the canvas placeholder.
 * Twin of python/tests/test_host_rendering.py.
 */
import * as fs from "node:fs";
import { firefox } from "playwright-core";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import {
	BUNDLE_EXE,
	configOf,
	HOME,
	quietly,
	restoreDeps,
	SCRATCH,
	stubHost,
	utils,
	warnings,
} from "./launch-host.js";

const { NewContext } = await import("../src/sync_api.js");
const {
	BASELINE_OVERRIDES_PREF,
	CANVAS_PLACEHOLDER_TARGETS,
	FEATURE_BLOCKED_DEVICE,
	hasCanvasPlaceholder,
	hostGpu,
	WEBGPU_BLOCKLIST_PREF,
} = await import("../src/host_rendering.js");
type Gpu = import("../src/host_rendering.js").Gpu;
// Imported after launch-host, which has to set the cache directory first.
const { MODEL } = await import("./fpgen-setup.js");

const deps = utils.utilsDeps;
const HOST_GPU: Gpu = ["AMD", "Radeon HD 3200 Graphics, or similar"];
const OTHER_GPU: Gpu = ["NVIDIA Corporation", "GeForce GTX 980, or similar"];
const SOFTWARE_GPU: Gpu = ["Mesa", "llvmpipe, or similar"];
const WINDOWS_GPU: Gpu = [
	"Google Inc. (NVIDIA)",
	"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar",
];
const WINDOWS_SOFTWARE_GPU: Gpu = [
	"Google Inc. (Microsoft)",
	"ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0), or similar",
];

afterEach(() => {
	restoreDeps();
	vi.restoreAllMocks();
});
afterAll(() => fs.rmSync(SCRATCH, { recursive: true, force: true }));

/** A host whose Firefox renders on `gpu`; records every probe. */
function onHost(
	gpu: Gpu | null,
	osKey: "lin" | "win" = "lin",
): Array<[string, boolean]> {
	const probes: Array<[string, boolean]> = [];
	stubHost();
	deps.hostOsKey = () => osKey;
	deps.hostGpu = async (executablePath, headless) => {
		probes.push([executablePath, headless]);
		return gpu;
	};
	return probes;
}

async function launch(opts: Record<string, any>) {
	const options = await quietly(() =>
		utils.launchOptions({ env: { HOME }, i_know_what_im_doing: true, ...opts }),
	);
	return { options, config: configOf(options) };
}

const placeholder = (options: Record<string, any>) =>
	hasCanvasPlaceholder(options.firefoxUserPrefs);

/** [navigator.gpu exposed, requestAdapter() blocked] for these launch options. */
const webgpu = (options: Record<string, any>) => [
	options.firefoxUserPrefs["dom.webgpu.enabled"],
	options.firefoxUserPrefs[WEBGPU_BLOCKLIST_PREF] === FEATURE_BLOCKED_DEVICE,
];

const gpuOf = (config: Record<string, any>) => [
	config["webGl:vendor"],
	config["webGl:renderer"],
];

describe.skipIf(!MODEL.ok)("the host's OS", () => {
	it("a drawn identity claims the host GPU without noise", async () => {
		const probes = onHost(HOST_GPU);
		const { options, config } = await launch({ os: "linux" });

		expect(gpuOf(config)).toEqual(HOST_GPU);
		expect(placeholder(options)).toBe(false);
		expect(probes).toEqual([[BUNDLE_EXE, false]]);
	});

	it("a software renderer leaves the GPU to the draw", async () => {
		onHost(SOFTWARE_GPU);
		const { options, config } = await launch({ os: "linux" });

		expect(config["webGl:renderer"]).not.toContain("llvmpipe");
		expect(placeholder(options)).toBe(false);
	});

	it("a host GPU fpgen never recorded is not claimed", async () => {
		const unrecorded: Gpu = ["AMD", "Radeon Unrecorded, or similar"];
		onHost(unrecorded);
		const { config } = await launch({ os: "linux" });

		expect(gpuOf(config)).not.toEqual(unrecorded);
	});

	it("a pinned GPU is kept without a probe", async () => {
		const probes = onHost(HOST_GPU);
		const { config } = await launch({ os: "linux", webgl_config: OTHER_GPU });

		expect(gpuOf(config)).toEqual(OTHER_GPU);
		expect(probes).toEqual([]);
	});

	it("noise on request needs no probe", async () => {
		const probes = onHost(HOST_GPU);
		const { options } = await launch({ os: "linux", canvas_noise: true });

		expect(placeholder(options)).toBe(true);
		expect(probes).toEqual([]);
	});
});

describe.skipIf(!MODEL.ok)("another OS", () => {
	it("the canvas is covered without a probe", async () => {
		const probes = onHost(HOST_GPU);
		const { options } = await launch({ os: "windows" });

		expect(placeholder(options)).toBe(true);
		expect(probes).toEqual([]);
	});

	it("covering the canvas warns", async () => {
		onHost(HOST_GPU);
		const { error, warnings: caught } = await warnings.recordWarnings(() =>
			utils.launchOptions({ env: { HOME }, os: "windows" }),
		);
		if (error) throw error;

		expect(
			caught.some(
				(w) =>
					w.category === "LeakWarning" &&
					w.message.includes("canvas_noise=False"),
			),
		).toBe(true);
	});

	it("it can be turned off", async () => {
		onHost(HOST_GPU);
		const { options } = await launch({ os: "windows", canvas_noise: false });

		expect(placeholder(options)).toBe(false);
	});

	it("caller overrides are kept", async () => {
		onHost(HOST_GPU);
		const { options } = await launch({
			os: "windows",
			firefox_user_prefs: {
				[BASELINE_OVERRIDES_PREF]: "-MaxTouchPointsCollapse",
			},
		});

		expect(options.firefoxUserPrefs[BASELINE_OVERRIDES_PREF]).toBe(
			["-MaxTouchPointsCollapse", ...CANVAS_PLACEHOLDER_TARGETS].join(","),
		);
	});
});

describe.skipIf(!MODEL.ok)("WebGPU", () => {
	it("the host GPU on Windows keeps its adapter", async () => {
		onHost(WINDOWS_GPU, "win");
		const { options, config } = await launch({ os: "windows" });

		expect(gpuOf(config)).toEqual(WINDOWS_GPU);
		expect(webgpu(options)).toEqual([true, false]);
	});

	it("software rendering on Windows has no adapter", async () => {
		onHost(WINDOWS_SOFTWARE_GPU, "win");
		const { options } = await launch({ os: "windows" });

		expect(webgpu(options)).toEqual([true, true]);
	});

	it("Windows on another host has no adapter", async () => {
		onHost(HOST_GPU);
		const { options } = await launch({ os: "windows" });

		expect(webgpu(options)).toEqual([true, true]);
	});

	it("a pinned GPU has no adapter", async () => {
		onHost(WINDOWS_GPU, "win");
		const { options } = await launch({
			os: "windows",
			webgl_config: WINDOWS_SOFTWARE_GPU,
		});

		expect(webgpu(options)).toEqual([true, true]);
	});

	it("caller prefs are kept", async () => {
		onHost(HOST_GPU);
		const { options } = await launch({
			os: "linux",
			firefox_user_prefs: { "dom.webgpu.enabled": true },
		});

		expect(webgpu(options)).toEqual([true, false]);
	});

	it("Linux has no navigator.gpu", async () => {
		onHost(HOST_GPU);
		const { options } = await launch({ os: "linux" });

		expect(webgpu(options)).toEqual([false, false]);
	});

	it.each([
		[["Apple", "Apple M1, or similar"] as Gpu, true],
		[["Intel Inc.", "Intel(R) HD Graphics, or similar"] as Gpu, false],
	])("macOS has navigator.gpu on Apple Silicon only (%j)", async (gpu, exposed) => {
		onHost(HOST_GPU);
		const { options } = await launch({ os: "macos", webgl_config: gpu });

		expect(webgpu(options)).toEqual([exposed, exposed]);
	});
});

it("the probe ignores what the launcher adds to the environment", () => {
	// hostIdentity probes with the launch's env, which carries CAMOU_* and
	// FONTCONFIG_FILE; that must hit launchOptions' cached probe.
	const launch = vi
		.spyOn(firefox, "launch")
		.mockImplementation(() => new Promise(() => undefined));
	const first = hostGpu("/nonexistent/camoufox", true, { DISPLAY: ":0" });
	const second = hostGpu("/nonexistent/camoufox", true, {
		DISPLAY: ":0",
		CAMOU_CONFIG_1: "{}",
		FONTCONFIG_FILE: "/x",
	});

	expect(second).toBe(first);
	expect(launch).toHaveBeenCalledTimes(1);
});

function browserOnHost(gpu: Gpu | null) {
	const calls: { script?: string } = {};
	const browser = {
		version: () => "150.0.2",
		newContext: async () => ({
			addInitScript: async (script: string) => {
				calls.script = script;
			},
		}),
		_camoufoxHostIdentity: ["lin", gpu],
	};
	return { browser: browser as any, calls };
}

const rendererOf = (script?: string) =>
	/setWebGLRenderer\("([^"]+)"\)/.exec(script ?? "")?.[1];

describe.skipIf(!MODEL.ok)("contexts of a browser on the host", () => {
	it("a context claims the host OS and GPU", async () => {
		const { browser, calls } = browserOnHost(HOST_GPU);
		await NewContext(browser);

		expect(calls.script).toContain('setNavigatorPlatform("Linux');
		expect(rendererOf(calls.script)).toBe(HOST_GPU[1]);
	});

	it("a software host leaves the GPU to the draw", async () => {
		const { browser, calls } = browserOnHost(null);
		await NewContext(browser);

		expect(rendererOf(calls.script)).not.toContain("llvmpipe");
	});

	it("another OS throws", async () => {
		const { browser } = browserOnHost(HOST_GPU);
		await expect(NewContext(browser, { os: "windows" })).rejects.toThrow(
			"canvas_noise: true",
		);
	});

	it("a preset with another GPU throws", async () => {
		const { browser } = browserOnHost(HOST_GPU);
		const preset = {
			navigator: { platform: "Linux x86_64" },
			webgl: { unmaskedVendor: OTHER_GPU[0], unmaskedRenderer: OTHER_GPU[1] },
		};
		await expect(NewContext(browser, { preset })).rejects.toThrow(
			"canvas_noise: true",
		);
	});
});

describe("hostIdentity", () => {
	const identity = (noised: boolean, canvasNoise: boolean | undefined) => {
		const prefs: Record<string, any> = {};
		if (noised)
			prefs[BASELINE_OVERRIDES_PREF] = CANVAS_PLACEHOLDER_TARGETS.join(",");
		deps.hostOsKey = () => "lin";
		deps.hostGpu = async () => HOST_GPU;
		return utils.hostIdentity(
			{
				executablePath: "/nonexistent/camoufox",
				headless: true,
				env: {},
				firefoxUserPrefs: prefs,
			},
			canvasNoise,
		);
	};

	it("a browser without noise records the host", async () => {
		expect(await identity(false, undefined)).toEqual(["lin", HOST_GPU]);
	});

	it("a noised browser records nothing", async () => {
		expect(await identity(true, undefined)).toBeNull();
	});

	it.each([
		false,
		true,
	])("a caller's explicit choice (%s) records nothing", async (canvasNoise) => {
		expect(await identity(false, canvasNoise)).toBeNull();
	});
});
