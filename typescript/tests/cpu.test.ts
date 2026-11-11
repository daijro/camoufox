/**
 * Port of python/tests/test_cpu.py: cpu:arch and cpu:manufacturer, the CPU
 * whose arithmetic the page sees.
 *
 * Firefox never reports the CPU, but canvas pixels, Web Audio samples, encoded
 * Opus, relaxed-SIMD wasm and NaN signs differ between x86-64 and ARM64, and
 * canvas and Opus between Intel's and AMD's RCPPS/RSQRTPS (browser/tests/
 * cpu-probe). The CPU is part of the identity: drawn once with it, consistent
 * with its GPU and OS, and sent to the browser as general.cpu_identity.
 */
import { describe, expect, it } from "vitest";
import * as coherence from "../src/coherence.js";
import { setCpuDefault, X86_INTEL_SHARE } from "../src/fingerprints.js";
import { LAUNCHER_CONSTANTS } from "../src/paths.js";
import { ValueError } from "../src/pycompat.js";
import { cpuIdentityPref, osForCpu, vpxRealtimeOnly } from "../src/utils.js";
import { MODEL } from "./fpgen-setup.js";

const WIN_UA =
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0";
const NVIDIA =
	"ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar";
const APPLE = "Apple M1, or similar";

type Cpu = [unknown, unknown];

function drawn(renderer: string | null, os = "win", salt = 0, cores = 8): Cpu {
	const config: Record<string, unknown> = {
		"navigator.userAgent": WIN_UA,
		"navigator.hardwareConcurrency": cores,
	};
	if (renderer) config["webGl:renderer"] = renderer;
	setCpuDefault(config, os, salt);
	return [config["cpu:arch"] ?? null, config["cpu:manufacturer"] ?? null];
}

/** The distinct [arch, manufacturer] pairs, as Python's set of tuples. */
function distinct(cpus: Cpu[]): Set<string> {
	return new Set(cpus.map((c) => JSON.stringify(c)));
}

function pairs(...cpus: Cpu[]): Set<string> {
	return distinct(cpus);
}

describe("the caller's option", () => {
	it.each([
		[{ arch: "x86", manufacturer: "intel" }, "mac", ["x86", "intel"]],
		[{ arch: "arm", manufacturer: "apple" }, "mac", ["arm", "apple"]],
		[{ manufacturer: "apple" }, "mac", ["arm", "apple"]],
		[{ manufacturer: "amd" }, "win", ["x86", "amd"]],
		[{ arch: "arm", manufacturer: "qualcomm" }, "win", ["arm", "qualcomm"]],
		[{ manufacturer: "broadcom" }, "lin", ["arm", "broadcom"]],
		[{ manufacturer: "apple" }, "lin", ["arm", "apple"]],
		[{ arch: "x86" }, "lin", ["x86", null]],
	])("real machines resolve: %o on %s", (cpu, os, resolved) => {
		const got = coherence.resolveCpu(cpu, os);
		expect([got["cpu:arch"] ?? null, got["cpu:manufacturer"] ?? null]).toEqual(
			resolved,
		);
	});

	it.each([
		[{ arch: "x86", manufacturer: "amd" }, "mac"], // every x86 Mac is Intel
		[{ arch: "x86", manufacturer: "apple" }, "mac"], // Apple makes no x86 CPU
		[{ arch: "x86", manufacturer: "apple" }, "lin"],
		[{ arch: "arm", manufacturer: "intel" }, "win"],
		[{ arch: "arm", manufacturer: "amd" }, "lin"],
		[{ arch: "arm", manufacturer: "broadcom" }, "win"], // Windows on ARM is Snapdragon
		[{ arch: "arm", manufacturer: "qualcomm" }, "mac"],
		[{ manufacturer: "qualcomm" }, "mac"],
		[{ manufacturer: "cyrix" }, "win"],
		[{ arch: "riscv" }, "lin"],
		[{ arch: "x86", vendor: "intel" }, "win"],
		["arm", "win"],
	])("impossible machines are rejected: %o on %s", (cpu, os) => {
		expect(() => coherence.resolveCpu(cpu, os)).toThrow(ValueError);
	});

	it("words its errors as pythonlib does", () => {
		const message = (cpu: unknown, os: string) => {
			try {
				coherence.resolveCpu(cpu, os);
			} catch (e) {
				return (e as Error).message;
			}
			return null;
		};
		expect(message({ arch: "x86", manufacturer: "amd" }, "mac")).toBe(
			"no mac machine has a CPU made by 'amd'; on mac it is one of apple, intel",
		);
		expect(message({ manufacturer: "cyrix" }, "win")).toBe(
			"no windows machine has a CPU made by 'cyrix'; on windows it is one of amd, intel, qualcomm",
		);
		expect(message({ arch: "x86", manufacturer: "apple" }, "lin")).toBe(
			"no linux machine has an x86 CPU made by 'apple'; linux x86 CPUs are made by intel, amd",
		);
		expect(message({ arch: "riscv" }, "lin")).toBe(
			"cpu arch must be one of ('x86', 'arm'), not 'riscv'",
		);
		expect(message({ arch: "x86", vendor: "intel" }, "win")).toBe(
			"cpu takes 'arch' and 'manufacturer', not 'vendor'",
		);
		expect(message("arm", "win")).toBe(
			"cpu must be a dict such as {'arch': 'x86', 'manufacturer': 'intel'}, not 'arm'",
		);
	});

	it.skipIf(!MODEL.ok)(
		"an OS left open is drawn among those with a GPU for the CPU",
		async () => {
			// fpgen records Apple GPUs only on macOS and no ARM GPU on Windows, so
			// an ARM identity is a Mac or a Linux machine rendering in software.
			expect(await osForCpu({ arch: "arm" }, null)).toEqual(["macos", "linux"]);
			expect(await osForCpu({ manufacturer: "amd" }, null)).toEqual([
				"windows",
				"linux",
			]);
			expect(await osForCpu({ arch: "x86" }, ["macos", "linux"])).toEqual([
				"macos",
				"linux",
			]);
			await expect(osForCpu({ manufacturer: "amd" }, "macos")).rejects.toThrow(
				"cpu={'manufacturer': 'amd'}: no mac machine has a CPU made by 'amd'; on mac it is one of apple, intel",
			);
			expect(await osForCpu({ manufacturer: "qualcomm" }, null)).toBe("linux");
			await expect(
				osForCpu({ manufacturer: "qualcomm" }, "macos"),
			).rejects.toThrow(
				"cpu={'manufacturer': 'qualcomm'}: no mac machine has a CPU made by 'qualcomm'; on mac it is one of apple, intel",
			);
		},
	);

	it.each([
		[APPLE, "mac", "arm", "apple", true],
		[APPLE, "mac", "x86", "intel", false],
		["Radeon R9 200 Series, or similar", "mac", "arm", null, false],
		["Radeon R9 200 Series, or similar", "mac", "x86", "intel", true],
		["Intel(R) HD Graphics, or similar", "lin", "x86", "amd", false],
		["Radeon HD 3200 Graphics, or similar", "lin", "x86", "intel", false],
		[NVIDIA, "win", "x86", "amd", true],
		[NVIDIA, "win", "arm", "qualcomm", false], // no Snapdragon laptop has a GeForce
		[
			"ANGLE (Qualcomm, Adreno X1-85 GPU Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			"arm",
			"qualcomm",
			true,
		],
		["V3D 4.2", "lin", "arm", "broadcom", true],
		["V3D 4.2", "lin", "arm", "qualcomm", false],
		["llvmpipe, or similar", "lin", "arm", "ampere", true], // software rendering runs on any CPU
		["llvmpipe, or similar", "lin", "x86", "amd", true],
	])("the GPU must fit the CPU: %s on %s, %s %s", (renderer, os, arch, maker, fits) => {
		expect(coherence.gpuFitsCpu(renderer, os, arch, maker)).toBe(fits);
	});
});

describe("the default", () => {
	it("a discrete GPU draws Firefox's x86 split", () => {
		const draws = Array.from({ length: 4000 }, (_, s) =>
			drawn(NVIDIA, "win", s),
		);
		const share =
			draws.filter(([a, m]) => a === "x86" && m === "intel").length /
			draws.length;
		expect(distinct(draws)).toEqual(pairs(["x86", "intel"], ["x86", "amd"]));
		expect(Math.abs(share - X86_INTEL_SHARE)).toBeLessThan(0.03);
	});

	it("the draw is a pure function of the identity", () => {
		const draw = () =>
			Array.from({ length: 50 }, (_, s) => drawn(NVIDIA, "win", s));
		expect(draw()).toEqual(draw());
	});

	it("draws what pythonlib draws for the same identity", () => {
		// python: set_cpu_default over salts 0..39 of this identity
		const python = "iiiiiiaiiiaiiiiiiiiiiaiiiiiiiaiaiiiiaiai";
		expect(
			Array.from({ length: 40 }, (_, s) => drawn(NVIDIA, "win", s)),
		).toEqual([...python].map((c) => ["x86", c === "i" ? "intel" : "amd"]));
	});

	it.each([
		[
			"ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			["x86", "intel"],
		],
		[
			"ANGLE (Intel, Intel(R) HD Graphics 400 Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			["x86", "intel"],
		],
		["Intel(R) HD Graphics, or similar", "lin", ["x86", "intel"]],
		[
			"ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar",
			"win",
			["x86", "amd"],
		],
		["Radeon HD 3200 Graphics, or similar", "lin", ["x86", "amd"]],
		// every x86 Mac has an Intel CPU, whatever its GPU
		["Radeon R9 200 Series, or similar", "mac", ["x86", "intel"]],
		["Intel(R) HD Graphics 400, or similar", "mac", ["x86", "intel"]],
		[APPLE, "mac", ["arm", "apple"]],
		["V3D 4.2", "lin", ["arm", "broadcom"]],
		["Mali-G610", "lin", ["arm", null]], // several SoC makers ship Mali
	] as [
		string,
		string,
		Cpu,
	][])("the GPU decides the CPU: %s on %s", (renderer, os, cpu) => {
		const seen = Array.from({ length: 200 }, (_, s) => drawn(renderer, os, s));
		expect(distinct(seen)).toEqual(pairs(cpu));
	});

	it.each([
		10, 14, 18, 22, 28,
	])("a core count only Intel ships (%i) decides the x86 vendor", (cores) => {
		const draws = Array.from({ length: 200 }, (_, s) =>
			drawn(NVIDIA, "win", s, cores),
		);
		expect(distinct(draws)).toEqual(pairs(["x86", "intel"]));
	});

	it("an Intel-only core count says nothing about ARM", () => {
		// An M4 Pro reports 14.
		expect(drawn(APPLE, "mac", 0, 14)).toEqual(["arm", "apple"]);
		const config = {
			"cpu:arch": "arm",
			"cpu:manufacturer": "apple",
			"webGl:renderer": APPLE,
			"navigator.hardwareConcurrency": 14,
		};
		expect(coherence.cpuConflict(config, "mac")).toBeNull();
	});

	it("a core count both vendors ship leaves the draw open", () => {
		const draws = Array.from({ length: 200 }, (_, s) =>
			drawn(NVIDIA, "win", s, 16),
		);
		expect(distinct(draws)).toEqual(pairs(["x86", "intel"], ["x86", "amd"]));
	});

	it("keeps a caller's CPU", () => {
		const config: Record<string, unknown> = {
			"cpu:arch": "x86",
			"cpu:manufacturer": "amd",
			"webGl:renderer": NVIDIA,
		};
		setCpuDefault(config, "win");
		expect([config["cpu:arch"], config["cpu:manufacturer"]]).toEqual([
			"x86",
			"amd",
		]);
	});
});

describe("coherence", () => {
	it("repairs a CPU the GPU contradicts", () => {
		const config: Record<string, unknown> = {
			"cpu:arch": "x86",
			"cpu:manufacturer": "amd",
			"webGl:renderer": "Intel(R) HD Graphics, or similar",
		};
		coherence.apply(config, "lin");
		expect([config["cpu:arch"], config["cpu:manufacturer"]]).toEqual([
			"x86",
			"intel",
		]);
		const mac: Record<string, unknown> = {
			"cpu:arch": "x86",
			"cpu:manufacturer": "intel",
			"webGl:renderer": APPLE,
		};
		coherence.apply(mac, "mac");
		expect([mac["cpu:arch"], mac["cpu:manufacturer"]]).toEqual([
			"arm",
			"apple",
		]);
	});

	it("keeps and reports a caller's CPU", () => {
		const config: Record<string, unknown> = {
			"cpu:arch": "x86",
			"cpu:manufacturer": "amd",
			"webGl:renderer": "Intel(R) HD Graphics, or similar",
		};
		const left = coherence.apply(
			config,
			"lin",
			new Set(["cpu:arch", "cpu:manufacturer"]),
		);
		expect(config["cpu:manufacturer"]).toBe("amd");
		expect(left.map((v) => v.rule)).toEqual(["cpu-matches-hardware"]);
		expect(left[0].detail).toBe(
			"CPU amd x86 beside 'Intel(R) HD Graphics, or similar'",
		);
	});

	it("repairs an x86 vendor its core count contradicts", () => {
		const config: Record<string, unknown> = {
			"cpu:arch": "x86",
			"cpu:manufacturer": "amd",
			"webGl:renderer": NVIDIA,
			"navigator.hardwareConcurrency": 22,
		};
		expect(coherence.validate(config, "win").map((v) => v.detail)).toEqual([
			"CPU amd x86 with hardwareConcurrency 22, which only an Intel CPU reports",
		]);
		coherence.apply(config, "win");
		expect(config["cpu:manufacturer"]).toBe("intel");
	});

	it("the GPU decides before the core count", () => {
		const apu = "Radeon HD 3200 Graphics, or similar";
		expect(drawn(apu, "lin", 0, 14)).toEqual(["x86", "amd"]);
	});
});

describe("the pref", () => {
	it("the pref values are the patch's", () => {
		// CPU_IDENTITY_* in cpu-identity.patch (mozilla/CpuIdentity.h)
		expect(LAUNCHER_CONSTANTS.cpuIdentityPref).toEqual({
			"x86/intel": 1,
			"x86/amd": 2,
			arm: 3,
		});
		expect(
			cpuIdentityPref({ "cpu:arch": "x86", "cpu:manufacturer": "intel" }),
		).toBe(1);
		expect(
			cpuIdentityPref({ "cpu:arch": "x86", "cpu:manufacturer": "amd" }),
		).toBe(2);
		expect(
			cpuIdentityPref({ "cpu:arch": "arm", "cpu:manufacturer": "apple" }),
		).toBe(3);
		expect(cpuIdentityPref({ "cpu:arch": "arm" })).toBe(3);
		expect(cpuIdentityPref({})).toBe(0);
	});
});

describe("libvpx realtime-only", () => {
	// Mozilla configures libvpx --enable-realtime-only for win/aarch64 and
	// linux/arm64, not mac/arm64 (media/libvpx/generate_sources_mozbuild.sh)
	it("is on for ARM Windows and Linux only", () => {
		const arm = { "cpu:arch": "arm", "cpu:manufacturer": "qualcomm" };
		expect(vpxRealtimeOnly(arm, "win")).toBe(true);
		expect(vpxRealtimeOnly(arm, "lin")).toBe(true);
		expect(
			vpxRealtimeOnly(
				{ "cpu:arch": "arm", "cpu:manufacturer": "apple" },
				"mac",
			),
		).toBe(false);
		for (const os of ["win", "lin", "mac"]) {
			expect(
				vpxRealtimeOnly({ "cpu:arch": "x86", "cpu:manufacturer": "amd" }, os),
			).toBe(false);
		}
		expect(vpxRealtimeOnly({}, "lin")).toBe(false);
	});
});
