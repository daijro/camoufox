/**
 * Port of pythonlib/tests/test_coherence.py (the rule-level half; the
 * launch-level half lives with the launcher tests) and test_shipped_data.py.
 *
 * Every identity Camoufox can produce has to be a machine that could exist:
 * the pools are sampled independently, so an incoherent identity is assembled
 * rather than inherited, and cleaning the pools cannot prevent it.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import * as coherence from "../src/coherence.js";
import { fromPreset } from "../src/fingerprints.js";
import { LOCAL_DATA } from "../src/pkgman.js";
import { firefoxGpus } from "../src/webgl.js";
import { MODEL } from "./fpgen-setup.js";

const rules = (config: Record<string, any>, os: string) =>
	coherence.validate(config, os).map((v) => v.rule);

describe("rules", () => {
	it("Apple Silicon never has fewer than eight cores", () => {
		const config = {
			"webGl:renderer": "Apple M1, or similar",
			"navigator.hardwareConcurrency": 2,
		};
		expect(rules(config, "mac")).toEqual(["apple-silicon-cores"]);
		expect(coherence.apply(config, "mac")).toEqual([]);
		expect(config["navigator.hardwareConcurrency"]).toBe(8);
	});

	it("a Mac cannot report a Braswell Atom IGP", () => {
		expect(
			rules(
				{ "webGl:renderer": "Intel(R) HD Graphics 400, or similar" },
				"mac",
			),
		).toEqual(["gpu-matches-os"]);
	});

	it("a Mac cannot report an ANGLE renderer", () => {
		expect(
			rules(
				{
					"webGl:renderer":
						"ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0), or similar",
				},
				"mac",
			),
		).toEqual(["gpu-matches-os"]);
	});

	it("Windows renders through ANGLE", () => {
		expect(
			coherence.gpuFitsOs(
				"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11), or similar",
				"win",
			),
		).toBe(true);
		expect(coherence.gpuFitsOs("Apple M1, or similar", "win")).toBe(false);
	});

	it("Apple Silicon reports deep colour", () => {
		const config: Record<string, any> = {
			"webGl:renderer": "Apple M1, or similar",
			"screen.colorDepth": 24,
		};
		expect(rules(config, "mac")).toEqual(["color-depth"]);
		expect(coherence.apply(config, "mac")).toEqual([]);
		expect(config["screen.colorDepth"]).toBe(30);
		expect(config["screen.pixelDepth"]).toBe(30);
	});

	it("colour depth is 24 or 30", () => {
		const config = { "screen.colorDepth": 32 };
		expect(rules(config, "lin")).toEqual(["color-depth"]);
		expect(coherence.apply(config, "lin")).toEqual([]);
		expect(config["screen.colorDepth"]).toBe(24);
	});

	it("touch points are a digitiser count", () => {
		const config = { "navigator.maxTouchPoints": 256 };
		expect(rules(config, "win")).toEqual(["touch-points"]);
		expect(coherence.apply(config, "win")).toEqual([]);
		expect(config["navigator.maxTouchPoints"]).toBe(0);
		for (const real of [0, 1, 2, 5, 10]) {
			expect(
				coherence.validate({ "navigator.maxTouchPoints": real }, "win"),
			).toEqual([]);
		}
	});

	it("a Mac has no touchscreen", () => {
		expect(rules({ "navigator.maxTouchPoints": 5 }, "mac")).toEqual([
			"touch-points",
		]);
	});

	it("devicePixelRatio is a real display mode", () => {
		const config = { "window.devicePixelRatio": 1.8181818181818181 };
		expect(rules(config, "win")).toEqual(["device-pixel-ratio"]);
		expect(coherence.apply(config, "win")).toEqual([]);
		expect(config["window.devicePixelRatio"]).toBe(1.75);
		expect(coherence.validate({ "window.devicePixelRatio": 1 }, "lin")).toEqual(
			[],
		);
		expect(
			coherence.validate({ "window.devicePixelRatio": 2.5 }, "win"),
		).toEqual([]);
		expect(coherence.validate({ "window.devicePixelRatio": 2 }, "mac")).toEqual(
			[],
		);
		expect(rules({ "window.devicePixelRatio": 1.5 }, "mac")).toEqual([
			"device-pixel-ratio",
		]);
	});

	it("desktop screens are landscape", () => {
		const config = { "screen.width": 1440, "screen.height": 2560 };
		expect(rules(config, "win")).toEqual(["screen-shape"]);
		expect(coherence.repairScreenOrientation(config)).toBe(true);
		expect([config["screen.width"], config["screen.height"]]).toEqual([
			2560, 1440,
		]);
	});

	it("a phone viewport is not a desktop screen", () => {
		expect(rules({ "screen.width": 736, "screen.height": 414 }, "mac")).toEqual(
			["screen-shape"],
		);
	});

	it("avail never exceeds the screen", () => {
		const config = {
			"screen.width": 1920,
			"screen.height": 1080,
			"screen.availWidth": 2000,
		};
		expect(rules(config, "lin")).toEqual(["avail-bounds"]);
		expect(coherence.apply(config, "lin")).toEqual([]);
		expect(config["screen.availWidth"]).toBe(1920);
	});

	it("the platform agrees with the user agent arch", () => {
		expect(
			rules(
				{
					"navigator.userAgent":
						"Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
					"navigator.platform": "Linux armv81",
				},
				"lin",
			),
		).toEqual(["arch-agreement"]);
	});

	it("the viewport leaves room for the browser chrome", () => {
		const config = {
			"window.outerHeight": 801,
			"window.innerHeight": 717,
			"screen.availHeight": 1040,
		};
		expect(rules(config, "lin")).toEqual(["window-chrome"]);
		expect(coherence.apply(config, "lin")).toEqual([]);
		expect(config["window.outerHeight"]).toBe(
			717 + coherence.BROWSER_CHROME_HEIGHT,
		);
	});

	it("the real machines pass", () => {
		const real: Array<[string, Record<string, any>]> = [
			[
				"lin",
				{
					"navigator.userAgent":
						"Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
					"navigator.platform": "Linux x86_64",
					"navigator.hardwareConcurrency": 16,
					"navigator.maxTouchPoints": 0,
					"screen.width": 1920,
					"screen.height": 1080,
					"screen.colorDepth": 24,
					"webGl:renderer": "Radeon HD 3200 Graphics, or similar",
				},
			],
			[
				"win",
				{
					"navigator.platform": "Win32",
					"navigator.hardwareConcurrency": 16,
					"navigator.maxTouchPoints": 5,
					"screen.width": 1382,
					"screen.height": 864,
					"screen.colorDepth": 24,
					"webGl:renderer":
						"ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
				},
			],
			[
				"mac",
				{
					"navigator.platform": "MacIntel",
					"navigator.hardwareConcurrency": 10,
					"navigator.maxTouchPoints": 0,
					"screen.width": 2560,
					"screen.height": 1440,
					"screen.colorDepth": 30,
					"webGl:renderer": "Apple M1, or similar",
				},
			],
		];
		for (const [os, config] of real) {
			expect(coherence.validate(config, os), os).toEqual([]);
		}
	});

	it("drops a source GPU the OS cannot report, and only that", () => {
		const config: Record<string, any> = {
			"webGl:vendor": "Intel",
			"webGl:renderer": "Intel(R) HD Graphics 400, or similar",
			"screen.width": 1920,
		};
		const dropped = coherence.dropIncoherentSourceValues(config, "mac");
		expect(dropped.map((v) => v.rule)).toEqual(["gpu-matches-os"]);
		expect(config).toEqual({ "screen.width": 1920 });
	});
});

describe("shipped data (test_shipped_data.py)", () => {
	const OS_KEY: Record<string, string> = {
		macos: "mac",
		windows: "win",
		linux: "lin",
	};
	for (const file of [
		"fingerprint-presets.json",
		"fingerprint-presets-v150.json",
	]) {
		it(`every preset in ${file} is coherent as stored`, () => {
			const presets = JSON.parse(
				fs.readFileSync(path.join(LOCAL_DATA, file), "utf-8"),
			).presets as Record<string, any[]>;
			for (const [os, entries] of Object.entries(presets)) {
				expect(
					entries.length,
					`${file}/${os} has no presets left`,
				).toBeGreaterThan(0);
				entries.forEach((preset, i) => {
					const config = fromPreset(preset, "152", 0);
					const violations = coherence.validate(config, OS_KEY[os]);
					expect(
						violations,
						`${file} ${os}[${i}]: ${violations.map((v) => v.detail).join("; ")}`,
					).toEqual([]);
				});
			}
		});
	}

	for (const file of [
		"fingerprint-presets.json",
		"fingerprint-presets-v150.json",
	]) {
		// A preset records only its GPU's name; the WebGL parameters behind it
		// come from fpgen, and a GPU fpgen never saw from Firefox on that OS has
		// none, so launching it would borrow another device's.
		it.skipIf(!MODEL.ok)(`every preset GPU in ${file} has WebGL data`, () => {
			const presets = JSON.parse(
				fs.readFileSync(path.join(LOCAL_DATA, file), "utf-8"),
			).presets as Record<string, any[]>;
			for (const [os, entries] of Object.entries(presets)) {
				const known = new Set(
					firefoxGpus(
						os === "windows" ? "win" : os === "macos" ? "mac" : "lin",
					).map((gpu) => JSON.stringify(gpu)),
				);
				entries.forEach((preset, i) => {
					const gpu = [
						preset.webgl.unmaskedVendor,
						preset.webgl.unmaskedRenderer,
					];
					expect(
						known.has(JSON.stringify(gpu)),
						`${file} ${os}[${i}]: ${gpu[1]} has no WebGL data`,
					).toBe(true);
				});
			}
		});
	}
});
