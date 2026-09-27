/**
 * The identity layer's behaviour: ports of pythonlib/tests/
 * test_fingerprint_fixes.py, test_preset_appversion.py, test_voices.py,
 * test_font_distribution.py and the unit half of test_identity_salt.py.
 * Exact parity with Python is pinned separately in identity-golden.test.ts.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { InvalidIP } from "../src/exceptions.js";
import {
	appVersionFromUserAgent,
	audioSeedFromIdentity,
	buildInitScript,
	clampScreenToDisplay,
	clampWindowDimensions,
	clampWindowPosition,
	drawMediaDevices,
	fixHardwareConcurrency,
	fixNavigatorArch,
	fixScreenNoTaskbar,
	fromFpgen,
	fromPreset,
	generateContextFingerprint,
	generateFingerprint,
	generateRandomFontSubset,
	generateRandomVoiceSubset,
	getRandomPreset,
	identitySalt,
	identitySeed,
	normalizePresetVoices,
	PLAUSIBLE_CORE_COUNTS,
	type Preset,
	Screen,
	setMediaDevicesDefaults,
	WINDOWS_11_MARKER_FONTS,
} from "../src/fingerprints.js";
import { LOCAL_DATA } from "../src/pkgman.js";
import { MODEL } from "./fpgen-setup.js";

function data(name: string): any {
	return JSON.parse(fs.readFileSync(path.join(LOCAL_DATA, name), "utf-8"));
}

describe("fixNavigatorArch", () => {
	it("corrects armv81 to the UA arch", () => {
		const c: Record<string, any> = {
			"navigator.userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) ...",
			"navigator.platform": "Linux armv81",
			"navigator.oscpu": "Linux armv81",
		};
		fixNavigatorArch(c, "lin");
		expect(c["navigator.platform"]).toBe("Linux x86_64");
		expect(c["navigator.oscpu"]).toBe("Linux x86_64");
	});

	it("only runs on Linux, and only with a UA", () => {
		const mac = {
			"navigator.userAgent": "... Macintosh ...",
			"navigator.platform": "MacIntel",
		};
		fixNavigatorArch(mac, "mac");
		expect(mac["navigator.platform"]).toBe("MacIntel");
		const noUa = { "navigator.platform": "Linux armv81" };
		fixNavigatorArch(noUa, "lin");
		expect(noUa["navigator.platform"]).toBe("Linux armv81");
	});
});

describe("fixScreenNoTaskbar", () => {
	it("subtracts the taskbar when avail equals the screen", () => {
		const c: Record<string, number> = {
			"screen.width": 1920,
			"screen.height": 1080,
			"screen.availWidth": 1920,
			"screen.availHeight": 1080,
			"window.outerHeight": 1080,
			"window.innerHeight": 1040,
		};
		fixScreenNoTaskbar(c, "lin");
		expect(c["screen.availHeight"]).toBe(1080 - 27);
		expect(c["window.outerHeight"]).toBe(1053);
		expect(c["window.innerHeight"]).toBe(1053 - 40);
	});

	it("uses each OS's taskbar height", () => {
		for (const [os, px] of [
			["win", 40],
			["mac", 25],
			["lin", 27],
		] as const) {
			const c: Record<string, number> = {
				"screen.width": 1920,
				"screen.height": 1080,
				"screen.availWidth": 1920,
				"screen.availHeight": 1080,
			};
			fixScreenNoTaskbar(c, os);
			expect(c["screen.availHeight"]).toBe(1080 - px);
		}
	});

	it("is a no-op when avail is already below the screen", () => {
		const c = {
			"screen.width": 1920,
			"screen.height": 1080,
			"screen.availWidth": 1920,
			"screen.availHeight": 1040,
		};
		fixScreenNoTaskbar(c, "lin");
		expect(c["screen.availHeight"]).toBe(1040);
	});
});

describe("clampWindowDimensions", () => {
	it("clamps impossible geometry on both axes", () => {
		const c: Record<string, number> = {
			"screen.width": 1920,
			"screen.height": 1080,
			"screen.availWidth": 2000,
			"window.outerWidth": 2200,
			"window.innerWidth": 2100,
		};
		clampWindowDimensions(c);
		expect(c["screen.availWidth"]).toBe(1920);
		expect(c["window.outerWidth"]).toBe(1920);
		expect(c["window.innerWidth"]).toBeLessThanOrEqual(c["window.outerWidth"]);
	});

	it("preserves the chrome delta", () => {
		const c: Record<string, number> = {
			"screen.width": 1000,
			"window.outerWidth": 1200,
			"window.innerWidth": 1180,
		};
		clampWindowDimensions(c);
		expect(c["window.outerWidth"]).toBe(1000);
		expect(c["window.innerWidth"]).toBe(980);
	});

	it("leaves a valid hierarchy alone", () => {
		const c = {
			"screen.width": 1920,
			"screen.availWidth": 1920,
			"window.outerWidth": 1280,
			"window.innerWidth": 1264,
		};
		clampWindowDimensions(c);
		expect(c["window.outerWidth"]).toBe(1280);
		expect(c["window.innerWidth"]).toBe(1264);
	});
});

describe("clampScreenToDisplay", () => {
	it("shrinks the screen to the display, keeping the taskbar delta", () => {
		const c: Record<string, number> = {
			"screen.width": 2560,
			"screen.height": 1440,
			"screen.availWidth": 2560,
			"screen.availHeight": 1400,
		};
		clampScreenToDisplay(c, 1366, 768);
		expect(c).toEqual({
			"screen.width": 1366,
			"screen.height": 768,
			"screen.availWidth": 1366,
			"screen.availHeight": 728,
		});
	});

	it("ignores unset bounds and never drops avail below one", () => {
		const c = { "screen.width": 2560, "screen.height": 1440 };
		clampScreenToDisplay(c, null, null);
		expect(c).toEqual({ "screen.width": 2560, "screen.height": 1440 });
		const tall = { "screen.height": 2000, "screen.availHeight": 100 };
		clampScreenToDisplay(tall, null, 768);
		expect(tall["screen.availHeight"]).toBeGreaterThanOrEqual(1);
	});

	it("survives the clampWindowDimensions cascade", () => {
		const c: Record<string, number> = {
			"screen.width": 2560,
			"screen.height": 1440,
			"screen.availWidth": 2560,
			"screen.availHeight": 1400,
			"window.outerWidth": 1920,
			"window.outerHeight": 1055,
			"window.innerWidth": 1920,
			"window.innerHeight": 1000,
		};
		clampScreenToDisplay(c, 1366, 768);
		clampWindowDimensions(c);
		expect(c["window.outerWidth"]).toBeLessThanOrEqual(c["screen.availWidth"]);
		expect(c["screen.availWidth"]).toBeLessThanOrEqual(1366);
		expect(c["window.outerHeight"]).toBeLessThanOrEqual(
			c["screen.availHeight"],
		);
		expect(c["window.innerHeight"]).toBeLessThanOrEqual(
			c["window.outerHeight"],
		);
	});
});

describe("clampWindowPosition", () => {
	it("pulls the window back inside the screen, never negative", () => {
		const c: Record<string, number> = {
			"screen.width": 1366,
			"screen.height": 768,
			"window.outerWidth": 1366,
			"window.outerHeight": 728,
			"window.screenX": 250,
			"window.screenY": 281,
		};
		clampWindowPosition(c);
		expect([c["window.screenX"], c["window.screenY"]]).toEqual([0, 40]);
		const wide: Record<string, number> = {
			"screen.width": 800,
			"window.outerWidth": 1000,
			"window.screenX": 50,
		};
		clampWindowPosition(wide);
		expect(wide["window.screenX"]).toBe(0);
	});
});

describe("media devices", () => {
	it("draws common desktop devices, seeded by the identity", () => {
		const c: Record<string, any> = {
			"navigator.userAgent": "ua",
			"navigator.platform": "Win32",
		};
		setMediaDevicesDefaults(c);
		expect(c["mediaDevices:enabled"]).toBe(true);
		for (const [kind, key] of [
			["micros", "microphone"],
			["webcams", "webcam"],
			["speakers", "speaker"],
		]) {
			const n = c[`mediaDevices:${kind}`];
			expect(c[`mediaDevices:${key}Labels`]).toHaveLength(n);
			expect(c[`mediaDevices:${key}Groups`]).toHaveLength(n);
		}
		expect(c["mediaDevices:speakers"]).toBeGreaterThanOrEqual(1);
		expect(
			c["mediaDevices:speakerLabels"].every((s: string) => s.includes("(")),
		).toBe(true);
		const again: Record<string, any> = {
			"navigator.userAgent": "ua",
			"navigator.platform": "Win32",
		};
		setMediaDevicesDefaults(again);
		expect(again).toEqual(c);
		let mics = 0;
		let cams = 0;
		for (let i = 0; i < 400; i++) {
			const d: Record<string, any> = {
				"navigator.userAgent": `ua${i}`,
				"navigator.platform": "Win32",
			};
			setMediaDevicesDefaults(d);
			mics += d["mediaDevices:micros"] > 0 ? 1 : 0;
			cams += d["mediaDevices:webcams"] > 0 ? 1 : 0;
		}
		expect(mics / 400).toBeGreaterThan(0.8);
		expect(mics / 400).toBeLessThan(1.0);
		expect(cams / 400).toBeGreaterThan(0.55);
		expect(cams / 400).toBeLessThan(0.95);
	});

	it("labels devices in each OS's style", () => {
		const mac = drawMediaDevices("mac", 7);
		expect(
			mac["mediaDevices:microphoneLabels"].some((s: string) =>
				s.startsWith("Microphone ("),
			),
		).toBe(false);
		const lin = drawMediaDevices("lin", 7);
		for (const o of lin["mediaDevices:speakerLabels"]) {
			expect(lin["mediaDevices:microphoneLabels"]).toContain(`Monitor of ${o}`);
		}
		const win = drawMediaDevices("win", 11);
		if (win["mediaDevices:micros"] && win["mediaDevices:speakers"]) {
			expect(win["mediaDevices:microphoneGroups"][0]).toBe(
				win["mediaDevices:speakerGroups"][0],
			);
		}
		for (const os of ["win", "mac", "lin"]) {
			for (let seed = 0; seed < 50; seed++) {
				const d = drawMediaDevices(os, seed);
				const m: string[] = d["mediaDevices:microphoneLabels"];
				const cams: string[] = d["mediaDevices:webcamLabels"];
				expect(m).not.toContain("Default Audio Device");
				expect(cams).not.toContain("Default Video Device");
				expect(new Set(m).size).toBe(m.length);
				expect(new Set(cams).size).toBe(cams.length);
			}
		}
	});

	it("respects caller-set mediaDevices keys", () => {
		const c = { "mediaDevices:webcams": 5 };
		setMediaDevicesDefaults(c);
		expect(c).toEqual({ "mediaDevices:webcams": 5 });
	});
});

describe("fixHardwareConcurrency", () => {
	it("keeps a plausible draw the host can be pinned to", () => {
		for (const drawn of [4, 6, 8, 10, 12, 14, 16]) {
			const c = { "navigator.hardwareConcurrency": drawn };
			fixHardwareConcurrency(c, undefined, { cpuCount: 16, canPinHost: true });
			expect(c["navigator.hardwareConcurrency"]).toBe(drawn);
		}
	});

	it("snaps implausible draws down into the table", () => {
		for (const [drawn, want] of [
			[1, 4],
			[2, 4],
			[3, 4],
			[5, 4],
			[7, 6],
			[9, 8],
			[11, 10],
			[13, 12],
			[15, 14],
			[32, 16],
		]) {
			const c = { "navigator.hardwareConcurrency": drawn };
			fixHardwareConcurrency(c, undefined, { cpuCount: 16, canPinHost: true });
			expect(c["navigator.hardwareConcurrency"], String(drawn)).toBe(want);
		}
		const c = { "navigator.hardwareConcurrency": 2 };
		fixHardwareConcurrency(c, undefined, { cpuCount: 4, canPinHost: true });
		expect(c["navigator.hardwareConcurrency"]).toBe(4);
	});

	it("snaps host parallelism when it cannot pin", () => {
		for (const [host, want] of [
			[16, 16],
			[10, 10],
			[24, 24],
			[26, 24],
			[32, 32],
			[64, 32],
			[22, 22],
			[7, 6],
			[5, 4],
			[2, 4],
			[9, 8],
		]) {
			const c = { "navigator.hardwareConcurrency": 2 };
			fixHardwareConcurrency(c, undefined, {
				cpuCount: host,
				canPinHost: false,
			});
			expect(c["navigator.hardwareConcurrency"], String(host)).toBe(want);
		}
		const c = { "navigator.hardwareConcurrency": 32 };
		fixHardwareConcurrency(c, undefined, { cpuCount: 8, canPinHost: true });
		expect(c["navigator.hardwareConcurrency"]).toBe(8);
	});

	it("reports the host when the launch will not pin", () => {
		const c = { "navigator.hardwareConcurrency": 8 };
		fixHardwareConcurrency(c, false, { cpuCount: 16, canPinHost: true });
		expect(c["navigator.hardwareConcurrency"]).toBe(16);
	});

	it("reports the table floor on a small pinnable host", () => {
		for (const host of [1, 2, 3]) {
			for (const drawn of [1, 2, 3, 8]) {
				const c = { "navigator.hardwareConcurrency": drawn };
				fixHardwareConcurrency(c, undefined, {
					cpuCount: host,
					canPinHost: true,
				});
				expect(c["navigator.hardwareConcurrency"]).toBe(4);
			}
		}
	});

	it("leaves the draw without a host count", () => {
		const c = { "navigator.hardwareConcurrency": 8 };
		fixHardwareConcurrency(c, undefined, { cpuCount: null });
		expect(c["navigator.hardwareConcurrency"]).toBe(8);
	});

	it("keeps the recorded counts in the table", () => {
		for (const n of [18, 22, 28, 32])
			expect(PLAUSIBLE_CORE_COUNTS).toContain(n);
	});
});

describe("preset appVersion (test_preset_appversion.py)", () => {
	const preset = (platform: string, userAgent: string) => ({
		navigator: { platform, userAgent },
	});

	it("follows the preset platform", () => {
		for (const [platform, ua, want] of [
			[
				"Linux x86_64",
				"Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
				"5.0 (X11)",
			],
			[
				"Win32",
				"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
				"5.0 (Windows)",
			],
			[
				"MacIntel",
				"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0",
				"5.0 (Macintosh)",
			],
		]) {
			expect(
				fromPreset(preset(platform, ua), null, 0)["navigator.appVersion"],
			).toBe(want);
		}
	});

	it("keeps a captured appVersion, follows an unknown platform's UA", () => {
		const p: any = preset(
			"Win32",
			"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Firefox/152.0",
		);
		p.navigator.appVersion = "5.0 (Windows NT 10.0; Win64; x64)";
		expect(fromPreset(p, null, 0)["navigator.appVersion"]).toBe(
			"5.0 (Windows NT 10.0; Win64; x64)",
		);
		expect(
			fromPreset(
				preset(
					"iPhone",
					"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Gecko/20100101",
				),
				null,
				0,
			)["navigator.appVersion"],
		).toBe("5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)");
	});

	it("matches what Firefox reports", () => {
		for (const [ua, want] of [
			[
				"Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
				"5.0 (X11; Ubuntu)",
			],
			[
				"Mozilla/5.0 (Android 16; Mobile; rv:152.0) Gecko/152.0 Firefox/152.0",
				"5.0 (Android 16)",
			],
		]) {
			expect(appVersionFromUserAgent(ua)).toBe(want);
		}
	});

	it("leaves a user agent it cannot read alone", () => {
		expect(
			"navigator.appVersion" in
				fromPreset(preset("Win32", "not a user agent"), null, 0),
		).toBe(false);
	});

	it("rewrites the Firefox version when asked", () => {
		const c = fromPreset(
			preset(
				"Linux x86_64",
				"Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
			),
			"152",
			0,
		);
		expect(c["navigator.userAgent"]).toBe(
			"Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
		);
	});
});

const REQUIRED_VOICE_FIELDS = [
	"lang",
	"name",
	"voiceUri",
	"isDefault",
	"isLocalService",
];

describe("voices (test_voices.py)", () => {
	for (const os of ["macos", "windows", "linux"]) {
		it(`${os}: non-empty full objects, none marked default`, () => {
			const voices = generateRandomVoiceSubset(os, "en-US");
			expect(voices.length).toBeGreaterThan(0);
			for (const v of voices) {
				for (const f of REQUIRED_VOICE_FIELDS) expect(v).toHaveProperty(f);
			}
			expect(voices.some((v) => v.isDefault)).toBe(false);
		});
	}

	it("uses the Windows display language pack", () => {
		expect(generateRandomVoiceSubset("windows", "de-DE", 1)[0].lang).toBe(
			"de-DE",
		);
		expect(
			generateRandomVoiceSubset("windows", "en-US", 1)
				.slice(0, 3)
				.map((v) => v.name),
		).toEqual([
			"Microsoft David - English (United States)",
			"Microsoft Mark - English (United States)",
			"Microsoft Zira - English (United States)",
		]);
	});

	it("builds Linux speechd URIs like SpeechDispatcherService.cpp", () => {
		const lin = generateRandomVoiceSubset("linux", "en-US");
		for (const v of lin) {
			expect(v.voiceUri.startsWith("urn:moz-tts:speechd:")).toBe(true);
			expect(v.voiceUri.endsWith(`?${v.lang}`)).toBe(true);
			expect(v.isLocalService).toBe(true);
		}
		const gb = lin.find((v) => v.name === "English (Great Britain)");
		expect(gb?.voiceUri).toBe(
			"urn:moz-tts:speechd:English%20(Great%20Britain)?en-GB",
		);
	});

	it("is deterministic per seed and falls back to macOS for an unknown OS", () => {
		expect(generateRandomVoiceSubset("windows", "fr-FR", 5)).toEqual(
			generateRandomVoiceSubset("windows", "fr-FR", 5),
		);
		expect(generateRandomVoiceSubset("plan9", "en-US").length).toBeGreaterThan(
			0,
		);
	});

	it("normalizes preset voices", () => {
		const out = normalizePresetVoices(
			["Albert:en-US:local", "Alice:it-IT:local"],
			"macos",
		);
		for (const v of out) {
			for (const f of REQUIRED_VOICE_FIELDS) expect(v).toHaveProperty(f);
		}
		expect([out[0].name, out[0].lang]).toEqual(["Albert", "en-US"]);
		expect(out.filter((v) => v.isDefault)).toHaveLength(1);
		const obj = {
			name: "Alex",
			lang: "en-US",
			voiceUri: "urn:moz-tts:osx:alex",
			isDefault: true,
			isLocalService: true,
		};
		expect(normalizePresetVoices([obj], "macos")).toEqual([obj]);
	});
});

describe("font distribution (test_font_distribution.py)", () => {
	const OS_KEYS: Record<string, string> = {
		windows: "win",
		macos: "mac",
		linux: "lin",
	};
	const N = 1500;
	const BASES = data("font-bases.json");
	const GROUPS = data("font-groups.json");
	const REPORTABLE = data("fonts.json");
	const samples: Record<string, Set<string>[]> = {};
	for (const os of Object.keys(OS_KEYS)) {
		samples[os] = Array.from(
			{ length: N },
			(_, i) => new Set(generateRandomFontSubset(os, i)),
		);
	}
	const tolerance = (p: number, n = N, sigmas = 5.0, floor = 0.03) =>
		Math.max(floor, sigmas * Math.sqrt(Math.max(p * (1 - p), 1e-6) / n));
	const union = (sets: Iterable<string>[]) => {
		const out = new Set<string>();
		for (const s of sets) for (const x of s) out.add(x);
		return out;
	};
	const unitExclusive = (osKey: string, unit: any) => {
		const others = union(
			GROUPS[osKey]
				.filter((u: any) => u.id !== unit.id)
				.map((u: any) => u.fonts),
		);
		const inBase = union(BASES[osKey].map((b: any) => b.fonts));
		return new Set<string>(
			unit.fonts.filter((f: string) => !others.has(f) && !inBase.has(f)),
		);
	};

	for (const os of Object.keys(OS_KEYS)) {
		const key = OS_KEYS[os];
		it(`${os}: every draw contains one complete base`, () => {
			const bases = BASES[key].map((b: any) => new Set<string>(b.fonts));
			samples[os].forEach((fonts, i) => {
				const ok = bases.some((b: Set<string>) =>
					[...b].every((f) => fonts.has(f)),
				);
				expect(ok, `draw #${i}`).toBe(true);
			});
		});

		it(`${os}: base weights and unit probabilities match the manifest`, () => {
			const bases = BASES[key];
			if (bases.length >= 2) {
				for (const b of bases) {
					const others = union(
						bases.filter((o: any) => o.id !== b.id).map((o: any) => o.fonts),
					);
					const ex = b.fonts.filter((f: string) => !others.has(f));
					if (!ex.length) continue;
					const seen =
						samples[os].filter((fonts) => ex.every((f: string) => fonts.has(f)))
							.length / N;
					expect(Math.abs(seen - b.weight), `base ${b.id}`).toBeLessThanOrEqual(
						tolerance(b.weight),
					);
				}
			}
			let checked = 0;
			for (const unit of GROUPS[key]) {
				if (unit.requiresLocale) continue;
				const ex = unitExclusive(key, unit);
				if (!ex.size) continue;
				const hits = samples[os].filter((fonts) =>
					[...ex].some((f) => fonts.has(f)),
				).length;
				checked++;
				expect(
					Math.abs(hits / N - unit.prob),
					`unit ${unit.id}`,
				).toBeLessThanOrEqual(tolerance(unit.prob));
			}
			expect(checked).toBeGreaterThan(0);
		});

		it(`${os}: bundles are all-or-nothing, a-la-carte units piecemeal`, () => {
			let alacarte = 0;
			for (const unit of GROUPS[key]) {
				const ex = unitExclusive(key, unit);
				if (unit.kind === "bundle" && ex.size >= 2) {
					for (const fonts of samples[os]) {
						const present = [...ex].filter((f) => fonts.has(f)).length;
						expect(
							present === 0 || present === ex.size,
							`bundle ${unit.id}`,
						).toBe(true);
					}
				}
				if (unit.kind === "alacarte" && ex.size >= 4) {
					alacarte++;
					const counts = new Set(
						samples[os].map(
							(fonts) => [...ex].filter((f) => fonts.has(f)).length,
						),
					);
					expect(
						[...counts].some((c) => c > 0 && c < ex.size),
						`alacarte ${unit.id}`,
					).toBe(true);
				}
			}
			expect(alacarte).toBeGreaterThan(0);
		});

		it(`${os}: draws vary, stay renderable, repeat per seed, never duplicate`, () => {
			const lists = samples[os].map((s) => [...s].sort().join("\n"));
			const counts = new Map<string, number>();
			for (const l of lists) counts.set(l, (counts.get(l) ?? 0) + 1);
			expect(counts.size).toBeGreaterThanOrEqual(50);
			expect(Math.max(...counts.values()) / N).toBeLessThanOrEqual(0.5);
			expect(
				new Set(samples[os].map((s) => s.size)).size,
			).toBeGreaterThanOrEqual(5);
			const pool = new Set<string>(REPORTABLE[key]);
			for (const fonts of samples[os]) {
				for (const f of fonts) expect(pool.has(f), f).toBe(true);
			}
			for (const seed of [1, 7, 99]) {
				expect(generateRandomFontSubset(os, seed)).toEqual(
					generateRandomFontSubset(os, seed),
				);
			}
			for (let i = 0; i < 200; i++) {
				const list = generateRandomFontSubset(os, i);
				expect(new Set(list).size).toBe(list.length);
			}
		});
	}

	it("every Windows identity presents Windows 11", () => {
		for (let i = 0; i < 50; i++) {
			const fonts = new Set(generateRandomFontSubset("windows", i));
			for (const f of WINDOWS_11_MARKER_FONTS) expect(fonts.has(f)).toBe(true);
		}
	});

	it("a native identity claims only the OS base", () => {
		const native = generateRandomFontSubset("linux", 0, true);
		expect(native).toEqual(generateRandomFontSubset("linux", 99, true));
	});
});

describe("identity salt and seed (test_identity_salt.py)", () => {
	it("unpinned salts differ", () => {
		const config = {
			"navigator.userAgent": "x",
			"navigator.platform": "Win32",
			"screen.width": 1920,
			"screen.height": 1080,
			"navigator.hardwareConcurrency": 8,
		};
		const seeds = new Set(
			Array.from({ length: 200 }, () => identitySeed(config, identitySalt())),
		);
		expect(seeds.size).toBe(200);
	});

	it("the salt of equal objects is equal", () => {
		expect(identitySalt({ a: 1, b: 2 })).toBe(identitySalt({ b: 2, a: 1 }));
		const s = new Screen({ maxWidth: 1920, maxHeight: 1080 });
		expect(identitySalt(s)).toBe(
			identitySalt(new Screen({ maxWidth: 1920, maxHeight: 1080 })),
		);
	});

	it("derives the audio seed without losing precision", () => {
		// (ident * 2654435761 + 97) & 0xFFFFFFFF, checked with Python ints
		expect(audioSeedFromIdentity(4294967295)).toBe(1640531632);
		expect(audioSeedFromIdentity(0)).toBe(97);
	});

	it("a pinned preset reproduces its draws", () => {
		const preset = getRandomPreset("windows", "150") as Preset;
		expect(preset).not.toBeNull();
		const salt = identitySalt(preset);
		const a = fromPreset(structuredClone(preset), "150", salt);
		const b = fromPreset(structuredClone(preset), "150", salt);
		expect(a.fonts).toEqual(b.fonts);
		expect(a.voices).toEqual(b.voices);
	});
});

describe("buildInitScript", () => {
	it("guards every setter and always clears the WebRTC IP", () => {
		const script = buildInitScript({
			navigatorPlatform: "Win32",
			hardwareConcurrency: 8,
			screenWidth: 1920,
			screenHeight: 1080,
			fontList: ["Arial"],
			speechVoices: [{ name: "A" } as any],
		});
		for (const line of script.split("\n").slice(2, -1)) {
			expect(line).toMatch(
				/^ {2}if \(typeof w\.\w+ === "function"\) w\.\w+\(.*\);$/,
			);
		}
		expect(script).toContain('w.setWebRTCIPv4("")');
		expect(buildInitScript({})).not.toContain("setFontList");
	});

	it("hands an IPv4 WebRTC address to the IPv4 setter", () => {
		const script = buildInitScript({ webrtcIP: "203.0.113.7" });
		expect(script).toContain('w.setWebRTCIPv4("203.0.113.7")');
		expect(script).not.toContain("setWebRTCIPv6(");
	});

	it("hands an IPv6 WebRTC address to the IPv6 setter", () => {
		const script = buildInitScript({ webrtcIP: "2001:db8::7" });
		expect(script).toContain('w.setWebRTCIPv6("2001:db8::7")');
		expect(script.split("setWebRTCIPv6")[0]).not.toContain("2001:db8::7");
	});

	it("refuses an invalid WebRTC address", () => {
		expect(() => buildInitScript({ webrtcIP: "not-an-ip" })).toThrow(InvalidIP);
	});
});

describe("fromFpgen", () => {
	it("maps navigator/screen/window/headers and rewrites the Firefox version", () => {
		const config = fromFpgen(
			{
				navigator: {
					userAgent:
						"Mozilla/5.0 (X11; Linux x86_64; rv:146.0) Gecko/20100101 Firefox/146.0",
					platform: "Linux x86_64",
					hardwareConcurrency: 8,
					deviceMemory: "undefined",
				},
				screen: { width: 1920, height: 1080, availLeft: -3 },
				window: { screenX: 10, innerWidth: 1900 },
				headers: { "accept-encoding": ["gzip, deflate, br, zstd"] },
			},
			"152",
		);
		expect(config).toEqual({
			"navigator.userAgent":
				"Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
			"navigator.platform": "Linux x86_64",
			"navigator.hardwareConcurrency": 8,
			"screen.width": 1920,
			"screen.height": 1080,
			"screen.availLeft": 0,
			"window.screenX": 10,
			"window.screenY": 10,
			"headers.Accept-Encoding": "gzip, deflate, br, zstd",
		});
	});
});

describe.skipIf(!MODEL.ok)("fpgen generation (needs the model)", () => {
	it("generates a Firefox fingerprint for each OS", () => {
		for (const [os, platform] of [
			["windows", "Win32"],
			["macos", "MacIntel"],
			["linux", "Linux"],
		]) {
			const f = generateFingerprint({ os });
			expect(String(f.navigator.platform)).toContain(platform);
			expect(String(f.navigator.userAgent)).toContain("Firefox");
		}
	});

	it("does not carry a drawn scroll offset into the config", () => {
		// The browser returns screen.pageYOffset from scrollY on every read, so
		// a drawn value froze the page at one scroll position.
		const fingerprint = generateFingerprint({ os: "windows" });
		fingerprint.window = {
			...fingerprint.window,
			pageXOffset: 17,
			pageYOffset: 528,
		};
		const config = fromFpgen(fingerprint, "152");
		expect("screen.pageXOffset" in config).toBe(false);
		expect("screen.pageYOffset" in config).toBe(false);
	});

	it("honours the screen bound, best-effort", () => {
		const f = generateFingerprint({ screen: new Screen({ maxWidth: 1400 }) });
		expect(f.screen.width).toBeLessThanOrEqual(1400);
		// A bound the pool cannot meet falls back to an unbounded draw.
		expect(() =>
			generateFingerprint({ screen: new Screen({ maxWidth: 1 }) }),
		).not.toThrow();
	});

	it("applies a custom window size, centred", () => {
		const f = generateFingerprint({ os: "linux", window: [800, 600] });
		expect([f.window.outerWidth, f.window.outerHeight]).toEqual([800, 600]);
	});

	it("accepts a list of OSes (Python raises InvalidConstraints here)", () => {
		// Divergence by design: fpgen passes predicates the casefolded value,
		// so Python's `v in {'Linux', 'Windows'}` never matches; TS compares
		// casefolded.
		const platforms = new Set<string>();
		for (let i = 0; i < 20; i++) {
			const f = generateFingerprint({ os: ["linux", "windows"] });
			const p = String(f.navigator.platform);
			expect(p.includes("Linux") || p === "Win32", p).toBe(true);
			platforms.add(p === "Win32" ? "win" : "lin");
		}
		expect(platforms.size).toBe(2);
	});

	it("rejects an unknown OS", () => {
		expect(() => generateFingerprint({ os: "plan9" })).toThrow(/Unknown OS/);
	});

	it("builds a context fingerprint from fpgen and from a preset", () => {
		const gen = generateContextFingerprint({ os: "windows", locale: "de-DE" });
		expect(gen.config.fonts.length).toBeGreaterThan(0);
		expect(gen.context_options.locale).toBe("de-DE");
		expect(gen.init_script).toContain("setNavigatorUserAgent");
		const preset = getRandomPreset("macos", "150");
		const fromP = generateContextFingerprint({
			preset,
			timezone: "Europe/Paris",
			config_overrides: { "audio:seed": 7 },
		});
		expect(fromP.context_options.timezoneId).toBe("Europe/Paris");
		expect(fromP.config["navigator.platform"]).toBe("MacIntel");
	});
});
