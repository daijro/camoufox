/**
 * Port of python/tests/test_cpu_vendor.py: cpu:vendor, the x86 CPU whose
 * RCPPS/RSQRTPS estimates the canvas shows (gfx.skia.cpu_vendor_estimates).
 */
import { describe, expect, it } from "vitest";
import * as coherence from "../src/coherence.js";
import { setCpuVendorDefault, X86_INTEL_SHARE } from "../src/fingerprints.js";
import { LAUNCHER_CONSTANTS } from "../src/paths.js";

const WIN_UA =
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0";
const NVIDIA =
	"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar";

function drawn(
	renderer: string | null,
	os = "win",
	salt = 0,
	cores = 8,
): unknown {
	const config: Record<string, unknown> = {
		"navigator.userAgent": WIN_UA,
		"navigator.hardwareConcurrency": cores,
	};
	if (renderer) config["webGl:renderer"] = renderer;
	setCpuVendorDefault(config, os, salt);
	return config["cpu:vendor"];
}

describe("cpu:vendor", () => {
	it("a discrete GPU draws Firefox's x86 split", () => {
		const draws = Array.from({ length: 4000 }, (_, s) =>
			drawn(NVIDIA, "win", s),
		);
		const share = draws.filter((v) => v === "intel").length / draws.length;
		expect(new Set(draws)).toEqual(new Set(["intel", "amd"]));
		expect(Math.abs(share - X86_INTEL_SHARE)).toBeLessThan(0.03);
	});

	it("draws what pythonlib draws for the same identity", () => {
		// python: set_cpu_vendor_default over salts 0..39 of this identity
		const python = [
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"amd",
			"intel",
			"intel",
			"intel",
			"amd",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"amd",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"intel",
			"amd",
			"intel",
			"amd",
			"intel",
			"intel",
			"intel",
			"intel",
			"amd",
			"intel",
			"amd",
			"intel",
		];
		expect(
			Array.from({ length: 40 }, (_, s) => drawn(NVIDIA, "win", s)),
		).toEqual(python);
	});

	it.each([
		[
			"ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			"intel",
		],
		[
			"ANGLE (Intel, Intel(R) HD Graphics 400 Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			"intel",
		],
		["Intel(R) HD Graphics, or similar", "lin", "intel"],
		[
			"ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			"amd",
		],
		["Radeon HD 3200 Graphics, or similar", "lin", "amd"],
		["Radeon R9 200 Series, or similar", "mac", "intel"],
		["Intel(R) HD Graphics 400, or similar", "mac", "intel"],
	])("%s on %s implies %s", (renderer, os, vendor) => {
		const seen = new Set(
			Array.from({ length: 200 }, (_, s) => drawn(renderer, os, s)),
		);
		expect(seen).toEqual(new Set([vendor]));
	});

	it("Apple Silicon has no x86 vendor", () => {
		expect(drawn("Apple M1, or similar", "mac")).toBeUndefined();
	});

	it("keeps a caller's vendor", () => {
		const config: Record<string, unknown> = {
			"cpu:vendor": "amd",
			"webGl:renderer": NVIDIA,
		};
		setCpuVendorDefault(config, "win");
		expect(config["cpu:vendor"]).toBe("amd");
	});

	it("coherence repairs a vendor its GPU contradicts", () => {
		const config: Record<string, unknown> = {
			"cpu:vendor": "amd",
			"webGl:renderer": "Intel(R) HD Graphics, or similar",
		};
		expect(coherence.validate(config, "lin").map((v) => v.rule)).toEqual([
			"cpu-vendor-matches-hardware",
		]);
		coherence.apply(config, "lin");
		expect(config["cpu:vendor"]).toBe("intel");
		const mac: Record<string, unknown> = {
			"cpu:vendor": "intel",
			"webGl:renderer": "Apple M1, or similar",
		};
		coherence.apply(mac, "mac");
		expect("cpu:vendor" in mac).toBe(false);
	});

	it.each([
		10, 14, 18, 22, 28,
	])("a core count only Intel ships (%i) decides the vendor", (cores) => {
		const draws = new Set(
			Array.from({ length: 200 }, (_, s) => drawn(NVIDIA, "win", s, cores)),
		);
		expect(draws).toEqual(new Set(["intel"]));
	});

	it("a core count both vendors ship leaves the draw open", () => {
		const draws = new Set(
			Array.from({ length: 200 }, (_, s) => drawn(NVIDIA, "win", s, 16)),
		);
		expect(draws).toEqual(new Set(["intel", "amd"]));
	});

	it("the GPU decides before the core count", () => {
		const apu = "Radeon HD 3200 Graphics, or similar";
		expect(drawn(apu, "lin", 0, 14)).toBe("amd");
		const config: Record<string, unknown> = {
			"cpu:vendor": "amd",
			"webGl:renderer": apu,
			"navigator.hardwareConcurrency": 14,
		};
		expect(coherence.validate(config, "lin").map((v) => v.rule)).toEqual([
			"cpu-vendor-matches-hardware",
		]);
	});

	it("coherence repairs a vendor its core count contradicts", () => {
		const config: Record<string, unknown> = {
			"cpu:vendor": "amd",
			"webGl:renderer": NVIDIA,
			"navigator.hardwareConcurrency": 22,
		};
		expect(coherence.validate(config, "win").map((v) => v.rule)).toEqual([
			"cpu-vendor-matches-hardware",
		]);
		coherence.apply(config, "win");
		expect(config["cpu:vendor"]).toBe("intel");
	});

	it("the pref values are the patch's", () => {
		expect(LAUNCHER_CONSTANTS.cpuVendorEstimatesPref).toEqual({
			intel: 1,
			amd: 2,
		});
	});
});
