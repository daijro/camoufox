/**
 * WebGL: ports of pythonlib/tests/test_webgl.py and
 * test_webgl_screen_consistency.py. The seeded draws themselves are pinned
 * against Python in identity-golden.test.ts. (test_no_coherent_gpu_raises is
 * not ported: it needs fpgen's trace replaced, which an ES module cannot do.)
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { gpuFitsOs } from "../src/coherence.js";
import {
	generateContextFingerprint,
	gpuScreenIsPlausible,
	isSoftwareRenderer,
	MODERN_SCREEN_FLOOR,
	raiseScreenToModernFloor,
	rendererBucket,
} from "../src/fingerprints.js";
import { orjsonDumps } from "../src/pycompat.js";
import { sampleWebglForScreen, toConfig, webglForGpu } from "../src/webgl.js";
import { MODEL } from "./fpgen-setup.js";
import { prerequisite } from "./prereq.js";

const OSES = ["win", "mac", "lin"] as const;
const SEEDS = Array.from({ length: 300 }, (_, i) => i);
const GTX_980_LINUX = [
	"NVIDIA Corporation",
	"NVIDIA GeForce GTX 980, or similar",
] as const;
const BASIC_RENDER_DRIVER = [
	"Google Inc. (Microsoft)",
	"ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0), or similar",
] as const;
// Limits WebGL1 and WebGL2 read from the same device.
const SHARED_LIMITS = [
	"3379",
	"3386",
	"34024",
	"34076",
	"34921",
	"34930",
	"35660",
	"35661",
	"36347",
	"36348",
	"36349",
];
const GTX_980_FIXTURE = path.resolve(
	path.dirname(fileURLToPath(import.meta.url)),
	"../../pythonlib/tests/data/webgl-gtx980-linux.json",
);

describe.skipIf(!MODEL.ok)("webgl (test_webgl.py)", () => {
	it.skipIf(
		!prerequisite(
			"pythonlib-source",
			fs.existsSync(GTX_980_FIXTURE),
			GTX_980_FIXTURE,
		),
	)("the converter reproduces the recorded device", () => {
		// What the retired webgl_data.db gave for this GPU. Parameters are
		// compared where the old row had a value, less the UNMASKED_* strings.
		const old = JSON.parse(fs.readFileSync(GTX_980_FIXTURE, "utf-8"));
		const fresh = JSON.parse(
			orjsonDumps(webglForGpu("lin", ...GTX_980_LINUX, 0), false),
		);
		expect(Object.keys(fresh).sort()).toEqual(Object.keys(old).sort());
		for (const key of Object.keys(old)) {
			if (key.endsWith(":parameters")) {
				for (const [pname, value] of Object.entries(old[key])) {
					if (value === null || pname === "37445" || pname === "37446")
						continue;
					expect(fresh[key][pname], `${key} ${pname}`).toEqual(value);
				}
			} else {
				expect(fresh[key], key).toEqual(old[key]);
			}
		}
	});

	it("the same seed draws the same device", () => {
		for (const os of OSES) {
			for (const seed of [0, 1, 12345]) {
				expect(sampleWebglForScreen(os, 1920, 1080, seed)).toEqual(
					sampleWebglForScreen(os, 1920, 1080, seed),
				);
			}
		}
		const gpu = ["AMD", "Radeon R9 200 Series, or similar"] as const;
		expect(webglForGpu("lin", ...gpu, 7)).toEqual(
			webglForGpu("lin", ...gpu, 7),
		);
	});

	it("the seed chooses among a GPU's recorded devices", () => {
		const drawn = new Set(
			Array.from({ length: 40 }, (_, s) =>
				orjsonDumps(
					webglForGpu("lin", "AMD", "Radeon R9 200 Series, or similar", s),
					false,
				),
			),
		);
		expect(drawn.size).toBeGreaterThan(1);
	});

	it.each(
		OSES,
	)("a synthetic %s draw is a hardware GPU the OS reports", (os) => {
		const renderers = new Set(
			SEEDS.map(
				(s) => sampleWebglForScreen(os, 1920, 1080, s)["webGl:renderer"],
			),
		);
		for (const renderer of renderers) {
			expect(isSoftwareRenderer(renderer), renderer).toBe(false);
			expect(renderer).not.toBe("Mozilla");
			expect(gpuFitsOs(renderer, os), renderer).toBe(true);
		}
		// A single GPU per OS is its own tell.
		expect(renderers.size).toBeGreaterThanOrEqual(2);
	});

	it.each(OSES)("a %s netbook screen never draws a discrete GPU", (os) => {
		for (const seed of SEEDS) {
			const renderer = sampleWebglForScreen(os, 1024, 600, seed)[
				"webGl:renderer"
			];
			expect(gpuScreenIsPlausible(renderer, 1024, 600), renderer).toBe(true);
		}
	});

	it.each(OSES)("%s WebGL2 comes from the same device as WebGL1", (os) => {
		for (const seed of SEEDS) {
			const config = sampleWebglForScreen(os, 1920, 1080, seed);
			for (const pname of SHARED_LIMITS) {
				expect(
					config["webGl:parameters"][pname],
					`seed ${seed} ${pname}`,
				).toEqual(config["webGl2:parameters"][pname]);
			}
		}
	});

	it("the GPU is pinned by vendor and renderer", () => {
		// "Mesa" and "AMD" both report this renderer on Linux.
		for (let seed = 0; seed < 40; seed++) {
			expect(
				webglForGpu("lin", "Mesa", "Radeon HD 3200 Graphics, or similar", seed)[
					"webGl:vendor"
				],
			).toBe("Mesa");
		}
	});

	it("a device without WebGL2 sets no webGl2 keys", () => {
		const config = webglForGpu("win", ...BASIC_RENDER_DRIVER, 0);
		expect(config.webGl2Enabled).toBe(false);
		expect(Object.keys(config).some((key) => key.startsWith("webGl2:"))).toBe(
			false,
		);
	});

	it("a GPU fpgen has never seen raises", () => {
		expect(() =>
			webglForGpu("win", "Apple", "Apple M1, or similar", 0),
		).toThrow(/No recorded WebGL data/);
	});

	const extensions = (os: string, key: string) =>
		Array.from(
			{ length: 100 },
			(_, s) =>
				new Set<string>(sampleWebglForScreen(os, 1920, 1080, s)[key] ?? []),
		);

	it("Windows keeps OVR_multiview2 on WebGL2", () => {
		expect(
			extensions("win", "webGl2:supportedExtensions").some((e) =>
				e.has("OVR_multiview2"),
			),
		).toBe(true);
	});

	it("Linux filters OVR_multiview2", () => {
		expect(
			extensions("lin", "webGl2:supportedExtensions").some((e) =>
				e.has("OVR_multiview2"),
			),
		).toBe(false);
	});
});

it("draft extensions are filtered on every OS", () => {
	const recorded = {
		vendor: "v",
		renderer: "r",
		contextAttributes: {},
		params: {},
		shaderPrecisionFormats: [],
		supportedExtensions: [
			"ANGLE_instanced_arrays",
			"WEBGL_multi_draw",
			"WEBGL_compressed_texture_etc1",
		],
	};
	const webgl2 = {
		...recorded,
		supportedExtensions: [
			"EXT_texture_norm16",
			"WEBGL_clip_cull_distance",
			"OVR_multiview2",
		],
	};
	for (const os of OSES) {
		const config = toConfig(recorded, webgl2, os);
		expect(config["webGl:supportedExtensions"]).toEqual([
			"ANGLE_instanced_arrays",
		]);
		expect(config["webGl2:supportedExtensions"]).toEqual(
			os === "win" ? ["OVR_multiview2"] : [],
		);
	}
});

// The three spellings Gecko emits for one discrete-NVIDIA bucket.
const NV_ANGLE =
	"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar";
const NV_PCIE = "NVIDIA GeForce GTX 980/PCIe/SSE2";
const NV_NOUVEAU = "GeForce GTX 980, or similar";
const AMD_IGP =
	"ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar";
const INTEL =
	"ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar";
const APPLE = "Apple M1, or similar";
const LLVMPIPE = "llvmpipe, or similar";

describe("WebGL <-> screen coherence (test_webgl_screen_consistency.py)", () => {
	it("every spelling of one GPU reduces to one bucket", () => {
		for (const r of [NV_ANGLE, NV_PCIE, NV_NOUVEAU]) {
			expect(rendererBucket(r)).toBe("GeForce GTX 980");
		}
	});

	it("the ANGLE vendor field does not decide the bucket", () => {
		expect(rendererBucket(AMD_IGP)).toBe("Radeon HD 3200 Graphics");
		expect(rendererBucket("Radeon HD 3200 Graphics, or similar")).toBe(
			"Radeon HD 3200 Graphics",
		);
	});

	it("the ANGLE Vulkan form is unwrapped", () => {
		expect(rendererBucket("ANGLE (Samsung Xclipse 920) on Vulkan")).toBe(
			"Samsung Xclipse 920",
		);
	});

	it("a discrete GPU is rejected on netbook panels only", () => {
		for (const r of [NV_ANGLE, NV_PCIE, NV_NOUVEAU]) {
			expect(gpuScreenIsPlausible(r, 1024, 600)).toBe(false);
		}
		for (const [w, h] of [
			[1024, 768],
			[1280, 720],
			[1280, 800],
			[1366, 768],
			[1920, 1080],
		]) {
			expect(gpuScreenIsPlausible(NV_ANGLE, w, h)).toBe(true);
		}
		for (const [w, h] of [
			[1024, 600],
			[800, 480],
			[1024, 576],
		]) {
			expect(gpuScreenIsPlausible(NV_ANGLE, w, h)).toBe(false);
		}
	});

	it("integrated parts, Apple silicon, raw model names and missing values are unconstrained", () => {
		expect(gpuScreenIsPlausible(INTEL, 1024, 600)).toBe(true);
		expect(gpuScreenIsPlausible(AMD_IGP, 1024, 600)).toBe(true);
		expect(gpuScreenIsPlausible(APPLE, 1280, 800)).toBe(true);
		expect(
			gpuScreenIsPlausible(
				"ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)",
				1024,
				600,
			),
		).toBe(true);
		expect(gpuScreenIsPlausible(null, 1920, 1080)).toBe(true);
		expect(gpuScreenIsPlausible(NV_ANGLE, null, null)).toBe(true);
	});

	it("software renderers are recognized and unconstrained", () => {
		for (const r of [
			LLVMPIPE,
			"ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0)",
			"ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)",
			"Generic Renderer",
		]) {
			expect(isSoftwareRenderer(r)).toBe(true);
			expect(gpuScreenIsPlausible(r, 1024, 600)).toBe(true);
		}
		for (const r of [NV_ANGLE, INTEL, APPLE, AMD_IGP]) {
			expect(isSoftwareRenderer(r)).toBe(false);
		}
	});

	it.skipIf(!MODEL.ok)("the sampled GPU is coherent with the screen", () => {
		for (const os of ["win", "mac", "lin"]) {
			for (let seed = 0; seed < 25; seed++) {
				const fp = sampleWebglForScreen(os, 1280, 800, seed);
				expect(gpuScreenIsPlausible(fp["webGl:renderer"], 1280, 800)).toBe(
					true,
				);
			}
		}
	});

	it("the screen floor lifts netbook geometry and keeps the taskbar gap", () => {
		const config: Record<string, number> = {
			"screen.width": 1024,
			"screen.height": 600,
			"screen.availWidth": 1024,
			"screen.availHeight": 560,
		};
		raiseScreenToModernFloor(config);
		expect([config["screen.width"], config["screen.height"]]).toEqual([
			...MODERN_SCREEN_FLOOR,
		]);
		expect(config["screen.height"] - config["screen.availHeight"]).toBe(40);
		expect(config["screen.width"] - config["screen.availWidth"]).toBe(0);
	});

	it("the screen floor leaves an adequate screen, or no screen, alone", () => {
		const config = {
			"screen.width": 1920,
			"screen.height": 1080,
			"screen.availWidth": 1920,
			"screen.availHeight": 1040,
		};
		const before = { ...config };
		raiseScreenToModernFloor(config);
		expect(config).toEqual(before);
		const empty = {};
		raiseScreenToModernFloor(empty);
		expect(empty).toEqual({});
	});

	it.skipIf(!MODEL.ok)("context fingerprints get the same treatment", () => {
		for (const os of ["windows", "macos", "linux"]) {
			for (let i = 0; i < 5; i++) {
				const { config } = generateContextFingerprint({ os });
				const r = config["webGl:renderer"];
				const w = config["screen.width"];
				const h = config["screen.height"];
				expect(r && w && h).toBeTruthy();
				expect(gpuScreenIsPlausible(r, w, h)).toBe(true);
				expect(w * h).toBeGreaterThan(1024 * 600);
			}
		}
	});
});
