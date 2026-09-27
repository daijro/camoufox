/**
 * Replays the Python identity layer's recorded outputs
 * (scripts/golden/identity_golden.py -> tests/fixtures/identity) through the
 * TypeScript port and requires the identical result: same seed and salt, same
 * fonts, voices, media devices, GPU, geometry and coherence verdicts.
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import * as coherence from "../src/coherence.js";
import * as fp from "../src/fingerprints.js";
import { pairwiseSum } from "../src/locales.js";
import { LOCAL_DATA } from "../src/pkgman.js";
import {
	crc32,
	formatOrjsonFloat,
	formatPyFloatRepr,
	num,
	orjsonDumps,
	PyFloat,
	parsePyJson,
	pyStrRepr,
	pySum,
	pySumFloats,
} from "../src/pycompat.js";
import { PyRandom, pyRandom } from "../src/pyrandom.js";
import * as webgl from "../src/webgl.js";
import { prerequisite } from "./prereq.js";

const FIXTURES = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	"fixtures",
	"identity",
);

function load(name: string, pyTyped = false): any {
	const file = path.join(FIXTURES, name);
	const raw = fs.readFileSync(file);
	const text = (name.endsWith(".gz") ? gunzipSync(raw) : raw).toString("utf-8");
	return pyTyped ? parsePyJson(text) : JSON.parse(text);
}

/**
 * Python's canon(): an int past 2**53 hashes as the float JavaScript would
 * hold (integral floats below it already print as ints here).
 */
function canon(value: unknown): unknown {
	if (typeof value === "bigint") return Number(value);
	if (value instanceof PyFloat) return value.value;
	if (Array.isArray(value)) return value.map(canon);
	if (value !== null && typeof value === "object") {
		return Object.fromEntries(
			Object.entries(value).map(([k, v]) => [k, canon(v)]),
		);
	}
	return value;
}

/** The golden hash: sha256 of the sorted-key orjson bytes, first 20 hex. */
function h(value: unknown): string {
	return createHash("sha256")
		.update(Buffer.from(orjsonDumps(canon(value)), "utf-8"))
		.digest("hex")
		.slice(0, 20);
}

function big(s: string | number): number | bigint {
	const n = BigInt(s);
	return n <= BigInt(Number.MAX_SAFE_INTEGER) &&
		n >= -BigInt(Number.MAX_SAFE_INTEGER)
		? Number(n)
		: n;
}

function clone<T>(v: T): T {
	return structuredClone(v);
}

function hashedLists(config: Record<string, any>): Record<string, any> {
	const out = { ...config };
	for (const key of ["fonts", "voices"]) {
		if (key in out) out[key] = { hash: h(out[key]), len: out[key].length };
	}
	return out;
}

describe("constants", () => {
	const c = load("constants.json");
	it("match the Python module", () => {
		expect(fp.FPGEN_DATA).toEqual(c.fpgenData);
		expect(fp.ESSENTIAL_FONTS_MACOS).toEqual(c.essentialMacos);
		expect(fp.ESSENTIAL_FONTS_WINDOWS).toEqual(c.essentialWindows);
		expect(fp.ESSENTIAL_FONTS_LINUX).toEqual(c.essentialLinux);
		expect(fp.MACOS_MARKER_FONTS).toEqual(c.markers.macos);
		expect(fp.WINDOWS_MARKER_FONTS).toEqual(c.markers.windows);
		expect(fp.LINUX_MARKER_FONTS).toEqual(c.markers.linux);
		expect([...fp.WINDOWS_11_MARKER_FONTS].sort()).toEqual(c.windows11Markers);
		expect(fp.PLAUSIBLE_CORE_COUNTS).toEqual(c.plausibleCoreCounts);
		expect(fp.MODERN_SCREEN_FLOOR).toEqual(c.modernScreenFloor);
		expect([...coherence.APPLE_SILICON_CORES].sort((a, b) => a - b)).toEqual(
			c.appleSiliconCores,
		);
		expect([...coherence.INTEL_MAC_IGP_CORES].sort((a, b) => a - b)).toEqual(
			c.intelMacIgpCores,
		);
		expect([...coherence.INTEL_MAC_DGPU_CORES].sort((a, b) => a - b)).toEqual(
			c.intelMacDgpuCores,
		);
		expect([...coherence.APPLE_SILICON_PANELS].sort()).toEqual(
			c.appleSiliconPanels,
		);
		// Iteration order matters: the dpr repair breaks ties by it.
		expect(coherence.PLAUSIBLE_DPR).toEqual(c.plausibleDpr);
		expect([...coherence.PLAUSIBLE_COLOR_DEPTH].sort()).toEqual(
			c.plausibleColorDepth,
		);
		expect(coherence.MAX_PLAUSIBLE_TOUCH_POINTS).toBe(c.maxTouchPoints);
		expect(coherence.BROWSER_CHROME_HEIGHT).toBe(c.browserChromeHeight);
		expect(coherence.RULES.map((r) => r.name)).toEqual(c.rules);
		expect([...fp.MAC_NOVELTY_VOICES].sort()).toEqual(c.macNovelty);
		expect([...fp.MAC_ELOQUENCE_VOICES].sort()).toEqual(c.macEloquence);
		expect(fp.PRESETS_V150_MIN_FF).toBe(c.presetsV150MinFf);
	});
});

describe("pyrandom (CPython random.Random)", () => {
	const { cases } = load("pyrandom.json.gz");
	it(`reproduces ${cases.length} seeded streams`, () => {
		for (const c of cases) {
			const r = new PyRandom(
				"int" in c.seed ? BigInt(c.seed.int) : (c.seed.str as string),
			);
			const label = JSON.stringify(c.seed);
			expect(
				Array.from({ length: 8 }, () => r.random()),
				label,
			).toEqual(c.random);
			for (const [k, v] of c.getrandbits) {
				expect(r.getrandbitsBig(k).toString(), `${label} bits ${k}`).toBe(v);
			}
			for (const [n, v] of c.randbelow) expect(r.randbelow(n)).toBe(v);
			for (const [args, v] of c.randrange) {
				expect(r.randrange(args[0], args[1], args[2] ?? 1)).toBe(v);
			}
			for (const [a, b, v] of c.randint) expect(r.randint(a, b)).toBe(v);
			const pop = [..."abcdefghijklmnopqrstuvwxyz"];
			expect(Array.from({ length: 5 }, () => r.choice(pop))).toEqual(c.choice);
			expect(r.choices(pop, { k: 6 })).toEqual(c.choices.plain);
			expect(
				r.choices(pop.slice(0, 5), {
					weights: [0.1, 0.5, 2.0, 1.25, 0.15],
					k: 6,
				}),
			).toEqual(c.choices.weights);
			expect(
				r.choices(pop.slice(0, 4), { cumWeights: [1, 3, 6, 10], k: 6 }),
			).toEqual(c.choices.cum_weights);
			const shuffled = Array.from({ length: 20 }, (_, i) => i);
			r.shuffle(shuffled);
			expect(shuffled).toEqual(c.shuffle);
			for (const [n, k, v] of c.sample) {
				expect(
					r.sample(
						Array.from({ length: n }, (_, i) => i),
						k,
					),
					`${label} sample(${n}, ${k})`,
				).toEqual(v);
			}
			expect(Array.from({ length: 3 }, () => r.uniform(-3.5, 10.25))).toEqual(
				c.uniform,
			);
			expect(r.random()).toBe(c.after);
		}
	});
});

describe("numpy sum", () => {
	const fx = load("numpy.json.gz");
	it("pairwise float64 sum", () => {
		for (const s of fx.sums)
			expect(pairwiseSum(s.values), `n=${s.values.length}`).toBe(s.sum);
	});
});

describe("python compatibility primitives", () => {
	const fx = load("pycompat.json.gz", true);
	it("orjson and repr float formatting", () => {
		for (const [x, orj, rep] of fx.floats) {
			expect(formatOrjsonFloat(num(x)), rep).toBe(orj);
			expect(formatPyFloatRepr(num(x))).toBe(rep);
		}
	});
	it("sum() over ints and floats", (ctx) => {
		// pySum() is sum() as 3.14 computes it; 3.12/3.13 round a mixed
		// int/float sum that loses precision differently in the last bit.
		const [major, minor] = fx.python;
		if (
			!prerequisite(
				"python-3.14",
				major * 100 + minor >= 314,
				`the goldens were recorded on Python ${major}.${minor}`,
			)
		)
			ctx.skip();
		for (const s of fx.sums) {
			const items = s.items.map((it: any) =>
				"i" in it
					? it.i
					: Number.isInteger(num(it.f))
						? new PyFloat(num(it.f))
						: num(it.f),
			);
			const got = pySum(items);
			if ("i" in s.result) expect(got).toBe(s.result.i);
			else expect(got).toBe(num(s.result.f));
		}
	});
	it("sum() over floats", () => {
		for (const s of fx.floatSums)
			expect(pySumFloats(s.values.map(num))).toBe(num(s.sum));
	});
	it("zlib.crc32", () => {
		for (const [s, v] of fx.crc32) expect(crc32(s)).toBe(v);
	});
	it("identity_salt over orjson bytes", () => {
		for (const c of fx.salts) {
			const value =
				"screen" in c
					? new fp.Screen({
							minWidth: c.screen[0],
							maxWidth: c.screen[1],
							minHeight: c.screen[2],
							maxHeight: c.screen[3],
						})
					: c.value;
			if (value === null) continue; // None draws a random salt
			expect(fp.identitySalt(value).toString(), orjsonDumps(c.value)).toBe(
				c.salt,
			);
		}
	});
	it("identity_seed", () => {
		for (const c of fx.seeds) {
			expect(fp.identitySeed(c.config, big(c.salt))).toBe(c.seed);
		}
	});
	it("repr(str)", () => {
		for (const [s, r] of fx.reprs) expect(pyStrRepr(s)).toBe(r);
	});
	it("identity_salt of full fpgen fingerprints", () => {
		const cases = load("fpgen-salts.json.gz", true);
		expect(cases.length).toBeGreaterThanOrEqual(3);
		for (const c of cases) {
			expect(fp.identitySalt(c.fingerprint).toString(), c.label).toBe(c.salt);
		}
	});
});

describe("font draws", () => {
	const { cases } = load("fonts.json.gz");
	it(`reproduces ${cases.length} font lists`, () => {
		for (const c of cases) {
			const fonts = fp.generateRandomFontSubset(
				c.os,
				big(c.seed),
				c.native ?? false,
				c.locale,
			);
			const label = `${c.os} seed ${c.seed} ${c.locale} native=${c.native}`;
			if (c.fonts) expect(fonts, label).toEqual(c.fonts);
			expect(fonts.length, label).toBe(c.len);
			expect(h(fonts), label).toBe(c.hash);
		}
	});
});

describe("voice draws", () => {
	const fx = load("voices.json.gz");
	it(`reproduces ${fx.cases.length} voice lists`, () => {
		for (const c of fx.cases) {
			const voices = fp.generateRandomVoiceSubset(c.os, c.locale, c.seed);
			const label = `${c.os} ${c.locale} seed ${c.seed}`;
			if (c.voices) expect(voices, label).toEqual(c.voices);
			expect(voices.length, label).toBe(c.len);
			expect(h(voices), label).toBe(c.hash);
		}
	});
	it("voice URIs", () => {
		for (const [osKey, name, lang, uri] of fx.uris) {
			expect(fp.voiceUri(osKey, name, lang)).toBe(uri);
		}
		// Every "Name:lang:type" entry in a voice manifest, in document order.
		const entriesOf = (node: unknown): string[] => {
			if (Array.isArray(node))
				return node.flatMap((item) =>
					typeof item === "string" && item.split(":").length >= 3
						? [item]
						: entriesOf(item),
				);
			if (node && typeof node === "object")
				return Object.values(node).flatMap(entriesOf);
			return [];
		};
		const manifests = JSON.parse(
			fs.readFileSync(path.join(LOCAL_DATA, "voice-manifests.json"), "utf-8"),
		) as Record<string, unknown>;
		for (const [osKey, manifest] of Object.entries(manifests)) {
			const uris = entriesOf(manifest).map((e) => {
				const parts = e.split(":");
				const lang = parts[parts.length - 2];
				const name = parts.slice(0, -2).join(":");
				return fp.voiceUri(osKey, name, lang);
			});
			expect(h(uris), osKey).toBe(fx.uriHashes[osKey]);
		}
	});
	it("preset voice normalization", () => {
		const presets: Record<string, any> = {};
		for (const file of [
			"fingerprint-presets.json",
			"fingerprint-presets-v150.json",
		]) {
			presets[file] = JSON.parse(
				fs.readFileSync(path.join(LOCAL_DATA, file), "utf-8"),
			).presets;
		}
		for (const c of fx.normalized) {
			if (c.extra) {
				expect(fp.normalizePresetVoices(c.extra, c.os)).toEqual(c.out);
				continue;
			}
			const out = fp.normalizePresetVoices(
				presets[c.file][c.os][c.index].speechVoices,
				c.os,
			);
			expect(out.length).toBe(c.len);
			expect(h(out)).toBe(c.hash);
		}
	});
});

describe("media devices", () => {
	const fx = load("media.json.gz");
	it(`reproduces ${fx.cases.length} device draws`, () => {
		for (const c of fx.cases) {
			const out = fp.drawMediaDevices(c.os, c.seed);
			if (c.out) expect(out).toEqual(c.out);
			expect(h(out), `${c.os} ${c.seed}`).toBe(c.hash);
		}
	});
	it("setMediaDevicesDefaults", () => {
		for (const c of fx.defaults) {
			const config = clone(c.config);
			fp.setMediaDevicesDefaults(config, big(c.salt));
			expect(h(config)).toBe(c.hash);
		}
	});
});

/** Python's exact(): sha256 of the orjson bytes, key order and number types included. */
function exact(value: unknown): string {
	return createHash("sha256")
		.update(Buffer.from(orjsonDumps(value, false), "utf-8"))
		.digest("hex")
		.slice(0, 20);
}

describe("webgl", () => {
	// Read as Python reads it: the recorded device's 1.0 must stay a float.
	const fx = load("webgl.json.gz", true);
	it("traces the same GPUs, in the same order", () => {
		for (const [osKey, gpus] of Object.entries(fx.gpus)) {
			expect(webgl.firefoxGpus(osKey), osKey).toEqual(gpus);
		}
	});
	it(`reproduces ${fx.forScreen.length} screen-coherent draws`, () => {
		for (const c of fx.forScreen) {
			const out = webgl.sampleWebglForScreen(c.os, c.w, c.h, big(c.seed));
			const label = `${c.os} ${c.w}x${c.h} seed ${c.seed}`;
			expect(out["webGl:renderer"], label).toBe(c.renderer);
			expect(exact(out), label).toBe(c.hash);
		}
	});
	it(`reproduces ${fx.forMachine.length} draws narrowed by the core count`, () => {
		for (const c of fx.forMachine) {
			const out = webgl.sampleWebglForScreen(
				c.os,
				c.w,
				c.h,
				big(c.seed),
				c.cores,
			);
			const label = `${c.os} ${c.w}x${c.h} cores ${c.cores} seed ${c.seed}`;
			expect(out["webGl:renderer"], label).toBe(c.renderer);
			expect(exact(out), label).toBe(c.hash);
		}
	});
	it(`reproduces ${fx.forGpu.length} draws for a named GPU`, () => {
		for (const c of fx.forGpu) {
			let got: any;
			try {
				const out = webgl.webglForGpu(c.os, c.vendor, c.renderer, c.seed);
				got = { ok: exact(out) };
			} catch (e) {
				got = { error: (e as Error).name, message: (e as Error).message };
			}
			expect(got, `${c.os} ${c.renderer} seed ${c.seed}`).toEqual(
				"ok" in c ? { ok: c.ok } : { error: c.error, message: c.message },
			);
		}
	});
	it("raises as Python does", () => {
		const { error, message } = fx.errors.unknownOs;
		expect(() => webgl.sampleWebglForScreen("bsd", 1920, 1080, 0)).toThrow(
			expect.objectContaining({ name: error, message }),
		);
	});
	it("converts a recorded device, filtering extensions per OS", () => {
		for (const c of fx.converted) {
			expect(
				exact(webgl.toConfig(fx.recorded, c.webgl2, c.os)),
				`${c.os} webgl2=${Array.isArray(c.webgl2) ? "[]" : "dict"}`,
			).toBe(c.hash);
		}
	});
});

function ret(v: unknown): unknown {
	return v === undefined ? null : v;
}

describe("geometry fixes", () => {
	const fx = load("geometry.json.gz");
	it(`reproduces ${fx.cases.length} random geometries`, () => {
		fx.cases.forEach((c: any, i: number) => {
			const fns: Record<string, (d: any) => unknown> = {
				fixScreenNoTaskbar: (d) => fp.fixScreenNoTaskbar(d, c.os),
				clampWindowDimensions: fp.clampWindowDimensions,
				clampScreenToDisplay: (d) => fp.clampScreenToDisplay(d, c.capW, c.capH),
				clampWindowPosition: fp.clampWindowPosition,
				raiseScreenToModernFloor: fp.raiseScreenToModernFloor,
				repairScreenOrientation: coherence.repairScreenOrientation,
			};
			for (const [name, fn] of Object.entries(fns)) {
				const d = clone(c.input);
				const r = fn(d);
				const want = c.out[name];
				const label = `case ${i} ${name}`;
				expect(ret(r), label).toEqual(want.ret);
				if (want.config) {
					expect(d, label).toEqual(want.config);
					expect(Object.keys(d), label).toEqual(Object.keys(want.config));
				} else {
					expect(h(d), label).toBe(want.hash);
					expect(h(Object.keys(d)), label).toBe(want.keys);
				}
			}
			const d = clone(c.input);
			if (coherence.screenIsImplausible(d)) {
				coherence.repairScreenOrientation(d);
				fp.raiseScreenToModernFloor(d);
			}
			fp.raiseScreenToModernFloor(d);
			fp.clampScreenToDisplay(d, c.capW, c.capH);
			fp.fixScreenNoTaskbar(d, c.os);
			fp.clampWindowDimensions(d);
			fp.clampWindowPosition(d);
			const want = c.out.pipeline;
			if (want.config) expect(d, `case ${i} pipeline`).toEqual(want.config);
			else expect(h(d), `case ${i} pipeline`).toBe(want.hash);
		});
	});
	it("fixNavigatorArch", () => {
		for (const [ua, plat, oscpu, target, platOut, oscpuOut] of fx.arch) {
			const c: Record<string, any> = { "navigator.userAgent": ua };
			if (plat !== null) c["navigator.platform"] = plat;
			if (oscpu !== null) c["navigator.oscpu"] = oscpu;
			fp.fixNavigatorArch(c, target);
			expect([
				c["navigator.platform"] ?? null,
				c["navigator.oscpu"] ?? null,
			]).toEqual([platOut, oscpuOut]);
		}
	});
	it(`fixHardwareConcurrency (${fx.hardwareConcurrency.length} host/draw combinations)`, () => {
		for (const [
			drawn,
			host,
			supported,
			canPin,
			out,
		] of fx.hardwareConcurrency) {
			const c: Record<string, any> =
				drawn === null ? {} : { "navigator.hardwareConcurrency": drawn };
			fp.fixHardwareConcurrency(c, canPin, {
				cpuCount: host,
				canPinHost: supported,
			});
			const got =
				"navigator.hardwareConcurrency" in c
					? c["navigator.hardwareConcurrency"]
					: "__missing__";
			expect(got, JSON.stringify([drawn, host, supported, canPin])).toEqual(
				out,
			);
		}
	});
});

describe("coherence", () => {
	const fx = load("coherence.json.gz");
	it("gpuFitsOs / gpuFitsMachine / gpuScreenIsPlausible / rendererBucket", () => {
		for (const [r, osKey, fits] of fx.fits) {
			expect(coherence.gpuFitsOs(r, osKey), `${r} ${osKey}`).toBe(fits);
		}
		for (const [r, osKey, cores, w, hh, fits] of fx.machine) {
			expect(
				coherence.gpuFitsMachine(r, osKey, cores, w, hh),
				`${r} ${osKey} ${cores} ${w}x${hh}`,
			).toBe(fits);
		}
		for (const [r, w, hh, plausible, software, bucket] of fx.gpuScreen) {
			expect(fp.gpuScreenIsPlausible(r, w, hh), `${r} ${w}x${hh}`).toBe(
				plausible,
			);
			expect(fp.isSoftwareRenderer(r)).toBe(software);
			if (r !== null) expect(fp.rendererBucket(r)).toBe(bucket);
		}
	});
	it(`validate / apply / drop over ${fx.cases.length} identities`, () => {
		fx.cases.forEach((c: any, i: number) => {
			const label = `case ${i} ${c.os}`;
			const pairs = (vs: coherence.Violation[]) =>
				vs.map((v) => [v.rule, v.detail]);
			const v = pairs(coherence.validate(clone(c.input), c.os));
			expect(
				v.map((x) => x[0]),
				label,
			).toEqual(c.rules);
			if (c.validateFull) expect(v, label).toEqual(c.validateFull);
			expect(h(v), label).toBe(c.validate);

			const applied = clone(c.input);
			const left = pairs(coherence.apply(applied, c.os));
			expect(
				left.map((x) => x[0]),
				label,
			).toEqual(c.apply);
			expect(h(left), label).toBe(c.applyHash);
			if (c.appliedFull) expect(applied, label).toEqual(c.appliedFull);
			expect(h(applied), label).toBe(c.applied);

			const dropped = clone(c.input);
			expect(
				pairs(coherence.dropIncoherentSourceValues(dropped, c.os)),
			).toEqual(c.dropped);
			expect(h(dropped), label).toBe(c.droppedConfig);
			expect(coherence.screenIsImplausible(c.input)).toBe(c.implausible);
		});
	});
});

describe("fromFpgen", () => {
	const fx = load("from-fpgen.json.gz");
	it(`reproduces ${fx.cases.length} configs`, () => {
		for (const c of fx.cases) {
			pyRandom.seed(c.moduleSeed);
			const config = fp.fromFpgen(clone(fx.inputs[c.input]), c.ffVersion);
			const label = `input ${c.input} ff ${c.ffVersion}`;
			expect(config, label).toEqual(c.config);
			expect(Object.keys(config), label).toEqual(c.configKeys);
			expect(fp.identitySeed(config, 12345678901234567890n), label).toBe(
				c.identitySeed,
			);
		}
	});
	it("handleWindowSize", () => {
		for (const c of fx.windowSize) {
			const d = clone(fx.inputs[c.input]);
			fp.handleWindowSize(d, c.w, c.h);
			expect(d).toEqual(c.out);
		}
	});
	it("Screen.asConditions", () => {
		// Python's 1080.0 is a float (rejected); JavaScript's 1080 is not.
		const probes = [800, 1366, 1920, 2560, null, "1920", null];
		for (const c of fx.screens) {
			const [minWidth, maxWidth, minHeight, maxHeight] = c.bounds;
			const conds = new fp.Screen({
				minWidth,
				maxWidth,
				minHeight,
				maxHeight,
			}).asConditions();
			expect(Object.keys(conds).sort()).toEqual(c.keys);
			for (const [key, want] of [
				["screen.width", c.width],
				["screen.height", c.height],
			]) {
				if (want === null) continue;
				probes.forEach((p, i) => {
					if (i === 4) return;
					expect(conds[key](p)).toBe(want[i]);
				});
			}
		}
	});
});

describe("presets", () => {
	const fx = load("presets.json.gz");
	const bundles: Record<string, any> = {};
	for (const file of [
		"fingerprint-presets.json",
		"fingerprint-presets-v150.json",
	]) {
		bundles[file] = JSON.parse(
			fs.readFileSync(path.join(LOCAL_DATA, file), "utf-8"),
		).presets;
	}
	const osKey: Record<string, string> = {
		macos: "mac",
		windows: "win",
		linux: "lin",
	};
	it(`fromPreset over ${fx.cases.length} bundled presets`, () => {
		for (const c of fx.cases) {
			pyRandom.seed(c.moduleSeed);
			const preset = bundles[c.file][c.os][c.index];
			const config = fp.fromPreset(clone(preset), c.ffVersion, big(c.salt));
			const label = `${c.file} ${c.os}[${c.index}] salt ${c.salt}`;
			expect(h(Object.keys(config)), label).toBe(c.keys);
			expect(h(config), label).toBe(c.hash);
			expect(
				coherence.validate(config, osKey[c.os]).map((v) => v.rule),
				label,
			).toEqual(c.validate);
		}
		for (const c of fx.full) {
			pyRandom.seed(c.index * 7);
			const config = fp.fromPreset(
				clone(bundles[c.file][c.os][c.index]),
				c.file.includes("v150") ? "152" : null,
				0,
			);
			expect(hashedLists(config)).toEqual(c.config);
		}
	});
	it("synthetic presets", () => {
		for (const c of fx.synthetic) {
			pyRandom.seed(c.moduleSeed);
			const config = fp.fromPreset(clone(c.preset), c.ffVersion, 99);
			expect(hashedLists(config)).toEqual(c.config);
		}
	});
	it("getRandomPreset", () => {
		for (const c of fx.random) {
			pyRandom.seed(c.moduleSeed);
			const preset = fp.getRandomPreset(c.os, c.ffVersion);
			expect(preset === null ? null : h(preset), JSON.stringify(c)).toBe(
				c.hash,
			);
		}
	});
	it("appVersion derivation and the presets file choice", () => {
		for (const [ua, want] of fx.appVersions) {
			expect(fp.appVersionFromUserAgent(ua), ua).toBe(want);
		}
		const inputs: Array<[string, string | number | null]> = [
			["None", null],
			["148", "148"],
			["149", "149"],
			["150.0.2", "150.0.2"],
			["abc", "abc"],
			["152", 152],
			["", ""],
			[" 150", " 150"],
		];
		for (const [key, value] of inputs) {
			expect(path.basename(fp.selectPresetsFile(value)), key).toBe(
				fx.presetsFile[key],
			);
		}
	});
});

describe("init script", () => {
	const { cases } = load("init-script.json");
	it("renders byte-identical scripts", () => {
		for (const c of cases) expect(fp.buildInitScript(c.values)).toBe(c.script);
	});
});
