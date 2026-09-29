/**
 * Ports of the pythonlib launch-layer tests:
 *   test_launch_environment.py, test_launch_geometry.py, test_humanize.py,
 *   test_viewport_default.py, test_executable_path_bundle.py,
 *   test_executable_path_version_warning.py, test_voices.py (launch half),
 *   test_identity_salt.py (launch half).
 *
 * The goldens (launch-golden.test.ts) pin exact output; these pin the
 * behaviours the Python suite names, with the same stubs.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { afterAll, afterEach, beforeEach, describe, expect, it } from "vitest";
import {
	BUNDLE,
	BUNDLE_EXE,
	configOf,
	fingerprints,
	HOME,
	isolateLaunch,
	quietly,
	restoreDeps,
	SCRATCH,
	stubHost,
	utils,
	warnings,
} from "./launch-host.js";
import { prerequisite } from "./prereq.js";

const { ensureModel } = await import("../src/fpgen/index.js");
const { OSError, PyFloat } = await import("../src/pycompat.js");
const { Version } = await import("../src/pkgman.js");
const { InvalidPropertyType } = await import("../src/exceptions.js");
const cpuAffinity = await import("../src/cpu_affinity.js");

let modelReady = true;
try {
	await ensureModel();
} catch (e) {
	modelReady = prerequisite("fpgen-model", false, String(e));
}

const deps = utils.utilsDeps;
// The real disk probe, captured before any test stubs it.
const realQuotaProbe = deps.stockProfileDiskCapacityKb;
const LINUX_UA =
	"Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0";
const MAC_UA =
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0";
const WIN_UA =
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0";

afterEach(() => restoreDeps());
afterAll(() => fs.rmSync(SCRATCH, { recursive: true, force: true }));

const launch = (opts: Record<string, any>) =>
	quietly(() => utils.launchOptions({ env: { HOME }, ...opts }));

/** The launch's config, and whether it emitted `category` containing `text`. */
async function launchWarning(
	opts: Record<string, any>,
	category: string,
	text: string,
): Promise<{ config: Record<string, any>; warned: boolean }> {
	const {
		result,
		error,
		warnings: caught,
	} = await warnings.recordWarnings(() =>
		utils.launchOptions({ env: { HOME }, ...opts }),
	);
	if (error) throw error;
	return {
		config: configOf(result as Record<string, any>),
		warned: caught.some(
			(w) => w.category === category && w.message.includes(text),
		),
	};
}
const REPORT = "github.com/daijro/camoufox/issues/new";

describe("test_launch_environment: virtual display", () => {
	beforeEach(() => isolateLaunch());

	const withVirtualDisplay = (extra: Record<string, any> = {}) =>
		launch({
			virtual_display: ":4242",
			headless: true,
			block_webgl: true,
			i_know_what_im_doing: true,
			...extra,
		});

	it("does not mutate the process environment", async () => {
		const keys = [
			"DISPLAY",
			"GDK_BACKEND",
			"WAYLAND_DISPLAY",
			"MOZ_ENABLE_WAYLAND",
		];
		const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
		delete process.env.DISPLAY;
		process.env.GDK_BACKEND = "wayland";
		process.env.WAYLAND_DISPLAY = "wayland-0";
		process.env.MOZ_ENABLE_WAYLAND = "1";
		try {
			const before = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
			const options = await quietly(() =>
				utils.launchOptions({
					virtual_display: ":4242",
					headless: true,
					block_webgl: true,
					i_know_what_im_doing: true,
				}),
			);
			expect(Object.fromEntries(keys.map((k) => [k, process.env[k]]))).toEqual(
				before,
			);
			expect(options.env.DISPLAY).toBe(":4242");
			expect(options.env.GDK_BACKEND).toBe("x11");
			expect("WAYLAND_DISPLAY" in options.env).toBe(false);
			expect(options.env.MOZ_ENABLE_WAYLAND).toBe("0");
		} finally {
			for (const [k, v] of Object.entries(saved)) {
				if (v === undefined) delete process.env[k];
				else process.env[k] = v;
			}
		}
	});

	it("does not mutate the caller's environment", async () => {
		const callerEnv = {
			UNCHANGED: "value",
			GDK_BACKEND: "wayland",
			WAYLAND_DISPLAY: "wayland-0",
			MOZ_ENABLE_WAYLAND: "1",
		};
		const before = { ...callerEnv };
		const options = await withVirtualDisplay({ env: callerEnv });
		expect(callerEnv).toEqual(before);
		expect(options.env.UNCHANGED).toBe("value");
		expect(options.env.DISPLAY).toBe(":4242");
		expect(options.env.GDK_BACKEND).toBe("x11");
		expect("WAYLAND_DISPLAY" in options.env).toBe(false);
		expect(options.env.MOZ_ENABLE_WAYLAND).toBe("0");
	});
});

describe("test_launch_environment: prefs", () => {
	beforeEach(() => isolateLaunch());

	const prefsFor = async (opts: Record<string, any>) =>
		(await launch({ i_know_what_im_doing: true, ...opts })).firefoxUserPrefs;
	const ua = (u: string, config: Record<string, any> = {}) => ({
		config: { "navigator.userAgent": u, ...config },
	});

	describe("font fallback async pref (Linux only)", () => {
		const PREF = "gfx.font_rendering.fallback.async";
		it("linux disables it", async () => {
			expect((await prefsFor(ua(LINUX_UA)))[PREF]).toBe(false);
		});
		it("macOS keeps it", async () => {
			expect(PREF in (await prefsFor(ua(MAC_UA)))).toBe(false);
		});
		it("windows keeps it", async () => {
			expect(PREF in (await prefsFor(ua(WIN_UA)))).toBe(false);
		});
		it("the caller's pref wins", async () => {
			const prefs = await prefsFor({
				...ua(LINUX_UA),
				firefox_user_prefs: { [PREF]: true },
			});
			expect(prefs[PREF]).toBe(true);
		});
	});

	describe("toggle settings are written both ways (test_launch_environment.py)", () => {
		// A persistent profile keeps a user.js pref in prefs.js, so a toggle that
		// only wrote when on stayed on after the flag was removed.
		const TOGGLES: [string, string, unknown, unknown][] = [
			["block_webrtc", "media.peerconnection.enabled", true, false],
			["block_images", "permissions.default.image", 1, 2],
			[
				"disable_coop",
				"browser.tabs.remote.useCrossOriginOpenerPolicy",
				true,
				false,
			],
		];
		for (const [flag, pref, stock, toggled] of TOGGLES) {
			it(`${flag} off writes the stock ${pref}`, async () => {
				expect((await prefsFor(ua(LINUX_UA)))[pref]).toBe(stock);
			});
			it(`${flag} on writes the toggled ${pref}`, async () => {
				expect((await prefsFor({ ...ua(LINUX_UA), [flag]: true }))[pref]).toBe(
					toggled,
				);
			});
			it(`the caller's ${pref} wins`, async () => {
				const prefs = await prefsFor({
					...ua(LINUX_UA),
					firefox_user_prefs: { [pref]: toggled },
				});
				expect(prefs[pref]).toBe(toggled);
			});
		}
	});

	describe("UI locale follows the Intl locale", () => {
		const PREF = "intl.locale.requested";
		it("a default identity pins en-US", async () => {
			expect((await prefsFor(ua(LINUX_UA)))[PREF]).toBe("en-US");
		});
		it("a spoofed locale selects the matching UI locale", async () => {
			// handle_locale adds the likely script (the language's Suppress-Script).
			expect((await prefsFor({ ...ua(LINUX_UA), locale: "fr-FR" }))[PREF]).toBe(
				"fr-Latn-FR",
			);
			expect((await prefsFor({ ...ua(LINUX_UA), locale: "pt-BR" }))[PREF]).toBe(
				"pt-Latn-BR",
			);
		});
		it("the first of several locales wins", async () => {
			expect(
				(await prefsFor({ ...ua(LINUX_UA), locale: "de-DE, en-US" }))[PREF],
			).toBe("de-Latn-DE");
		});
		it("a geoip-style config locale is used", async () => {
			const config = { "locale:language": "ja", "locale:region": "JP" };
			expect((await prefsFor(ua(LINUX_UA, config)))[PREF]).toBe("ja-JP");
		});
		it("keeps a script subtag", async () => {
			const config = {
				"locale:language": "zh",
				"locale:script": "Hant",
				"locale:region": "TW",
			};
			expect((await prefsFor(ua(LINUX_UA, config)))[PREF]).toBe("zh-Hant-TW");
		});
		it("the caller's pref wins", async () => {
			const prefs = await prefsFor({
				...ua(LINUX_UA),
				locale: "fr-FR",
				firefox_user_prefs: { [PREF]: "de" },
			});
			expect(prefs[PREF]).toBe("de");
		});
	});

	describe("prefs reach startup (CAMOU_PREFS_<n>)", () => {
		it("passes the prefs as env", async () => {
			const opts = await launch({
				...ua(WIN_UA),
				locale: "fr-FR",
				i_know_what_im_doing: true,
			});
			const keys = Object.keys(opts.env)
				.filter((k) => k.startsWith("CAMOU_PREFS_"))
				.sort(
					(a, b) => Number(a.split("_").pop()) - Number(b.split("_").pop()),
				);
			expect(keys[0]).toBe("CAMOU_PREFS_1");
			const prefs = JSON.parse(keys.map((k) => opts.env[k]).join(""));
			expect(prefs).toEqual(opts.firefoxUserPrefs);
			expect(prefs["intl.locale.requested"]).toBe("fr-Latn-FR");
		});

		it("chunks large prefs in order (2047 on Windows)", () => {
			deps.osName = () => "win";
			const prefs = Object.fromEntries(
				Array.from({ length: 200 }, (_, i) => [
					`camoufox.test.pref${i}`,
					"x".repeat(50),
				]),
			);
			const env = utils.getPrefEnvVars(prefs);
			const values = Object.values(env);
			expect(values.length).toBeGreaterThan(1);
			expect(values.every((v) => v.length <= 2047)).toBe(true);
			const joined = Array.from(
				{ length: values.length },
				(_, i) => env[`CAMOU_PREFS_${i + 1}`],
			).join("");
			expect(JSON.parse(joined)).toEqual(prefs);
		});

		it("no prefs, no env", () => {
			expect(utils.getPrefEnvVars({})).toEqual({});
		});

		it("is ASCII, and round-trips non-ASCII values (test_identity_salt)", () => {
			const prefs = {
				"font.name.serif.ja": "游明朝",
				"intl.accept_languages": "fr-FR, fr",
			};
			const env = utils.getPrefEnvVars(prefs);
			const joined = Array.from(
				{ length: Object.keys(env).length },
				(_, i) => env[`CAMOU_PREFS_${i + 1}`],
			).join("");
			expect([...joined].every((c) => c.charCodeAt(0) < 0x80)).toBe(true);
			expect(JSON.parse(joined)).toEqual(prefs);
			// json.dumps(ensure_ascii=True): lowercase \u escapes.
			expect(joined).toContain("\\u6e38\\u660e\\u671d");
		});
	});

	describe("Windows scrollbars follow the version the fonts present", () => {
		const PREF = "ui.useOverlayScrollbars";
		const prefs = (fonts: string[], u = WIN_UA) => prefsFor(ua(u, { fonts }));
		it("Windows 11 fonts get overlay scrollbars", async () => {
			expect((await prefs(["Arial", "Segoe UI Variable Text"]))[PREF]).toBe(1);
		});
		it("Windows 10 fonts get classic ones", async () => {
			expect((await prefs(["Arial", "Segoe UI", "Calibri"]))[PREF]).toBe(0);
		});
		it("other OSes get overlay", async () => {
			expect((await prefs(["DejaVu Sans"], LINUX_UA))[PREF]).toBe(1);
		});
	});

	describe("storage quota follows the host disk", () => {
		const PREF = "dom.quotaManager.temporaryStorage.fixedLimit";
		/** The real probe (isolateLaunch stubs it), over a stubbed disk. */
		const withDisk = (total: number | Error) => {
			deps.stockProfileDiskCapacityKb = realQuotaProbe;
			deps.diskTotal = () => {
				if (total instanceof Error) throw total;
				return total;
			};
		};
		const quotaPrefs = (extra: Record<string, any> = {}) =>
			prefsFor({ ...ua(LINUX_UA), ...extra });

		it("is half the host disk, in KB", async () => {
			const capacity = 512 * 1024 ** 3;
			withDisk(capacity);
			expect((await quotaPrefs())[PREF]).toBe(Math.floor(capacity / 2 / 1024));
		});

		it("a small disk reports less than the 10 GiB cap", async () => {
			const capacity = 40 * 1000 ** 3;
			withDisk(capacity);
			const limitKb = (await quotaPrefs())[PREF];
			const groupLimit = Math.min(
				Math.floor((limitKb * 1024) / 5),
				10 * 1024 ** 3,
			);
			expect(groupLimit).toBe(Math.floor(capacity / 2 / 5));
			expect(groupLimit).toBeLessThan(10 * 1024 ** 3);
		});

		it("a multi-terabyte disk stays in int32", async () => {
			withDisk(16 * 1024 ** 4);
			const limitKb = (await quotaPrefs())[PREF];
			expect(limitKb).toBeLessThanOrEqual(2 ** 31 - 1);
			expect(Math.floor((limitKb * 1024) / 5)).toBeGreaterThanOrEqual(
				10 * 1024 ** 3,
			);
		});

		it("an unreadable disk leaves Gecko to measure", async () => {
			withDisk(new Error("no such device"));
			expect(PREF in (await quotaPrefs())).toBe(false);
		});

		it("the caller's pref wins", async () => {
			withDisk(512 * 1024 ** 3);
			expect(
				(await quotaPrefs({ firefox_user_prefs: { [PREF]: 1234 } }))[PREF],
			).toBe(1234);
		});
	});
});

describe("test_launch_environment: stock media defaults", () => {
	it("defaults are the JS API's no-override (null)", () => {
		expect(utils.STOCK_MEDIA_DEFAULTS).toEqual({
			colorScheme: null,
			reducedMotion: null,
			forcedColors: null,
			contrast: null,
		});
	});

	class FakeBrowser {
		calls: Array<[string, Record<string, any>]> = [];
		newPage(opts: Record<string, any> = {}) {
			this.calls.push(["newPage", opts]);
		}
		newContext(opts: Record<string, any> = {}) {
			this.calls.push(["newContext", opts]);
		}
	}

	it("newPage and newContext get them", () => {
		const browser = utils.attachStockMediaDefaults(new FakeBrowser());
		browser.newPage();
		browser.newContext();
		for (const [, opts] of browser.calls) {
			expect(opts).toEqual({
				colorScheme: null,
				reducedMotion: null,
				forcedColors: null,
				contrast: null,
			});
		}
	});

	it("the caller's value wins", () => {
		const browser = utils.attachStockMediaDefaults(new FakeBrowser());
		browser.newContext({ colorScheme: "dark", forcedColors: "active" });
		const opts = browser.calls[0][1];
		expect(opts.colorScheme).toBe("dark");
		expect(opts.forcedColors).toBe("active");
		expect(opts.reducedMotion).toBeNull();
	});

	it("isMobile warns that Camoufox is desktop-only", async () => {
		const browser = utils.attachDesktopOnlyWarning(new FakeBrowser());
		for (const create of ["newPage", "newContext"] as const) {
			const { warnings: caught } = await warnings.recordWarnings(async () =>
				browser[create]({ isMobile: true }),
			);
			expect(
				caught.some(
					(w) =>
						w.category === "LeakWarning" &&
						w.message.includes("built for desktops"),
				),
			).toBe(true);
		}
		const { warnings: none } = await warnings.recordWarnings(async () =>
			browser.newContext({ isMobile: false }),
		);
		expect(none).toEqual([]);
	});
});

describe("test_viewport_default", () => {
	const opts = (blob: string) => {
		const chunks: string[] = [];
		for (let i = 0; i < blob.length; i += 10)
			chunks.push(blob.slice(i, i + 10));
		if (!chunks.length) chunks.push("");
		return {
			env: Object.fromEntries(
				chunks.map((c, i) => [`CAMOU_CONFIG_${i + 1}`, c]),
			),
		};
	};

	it.each([
		['{"window.outerWidth": 360}', true],
		['{"window.innerHeight": 740}', true],
		['{"screen.width": 360}', false],
		['{"navigator.userAgent": "x"}', false],
		["{}", false],
	])("detects window dimension spoofing in %s", (blob, expected) => {
		expect(utils.spoofsWindowDimensions(opts(blob))).toBe(expected);
	});

	it("reassembles chunks in index order", () => {
		const blob = `{"padding": "${"x".repeat(200)}", "window.outerWidth": 360}`;
		expect(utils.spoofsWindowDimensions(opts(blob))).toBe(true);
	});

	it("no env is not spoofed", () => {
		expect(utils.spoofsWindowDimensions({})).toBe(false);
	});

	class FakeBrowser {
		calls: Record<string, any>[] = [];
		newPage(o: Record<string, any> = {}) {
			this.calls.push(o);
			return "page";
		}
		newContext(o: Record<string, any> = {}) {
			this.calls.push(o);
			return "context";
		}
	}

	it("defaults to no viewport (viewport: null)", () => {
		const b = utils.attachNoViewportDefault(new FakeBrowser());
		b.newPage();
		b.newContext();
		expect(b.calls).toEqual([{ viewport: null }, { viewport: null }]);
	});

	it.each([
		[
			{ viewport: { width: 800, height: 600 } },
			{ viewport: { width: 800, height: 600 } },
		],
		[{ noViewport: false }, {}],
		[{ viewport: null }, { viewport: null }],
	])("the caller's explicit choice wins: %j", (override, expected) => {
		const b = utils.attachNoViewportDefault(new FakeBrowser());
		b.newPage(override);
		expect(b.calls).toEqual([expected]);
	});

	it("forwards other options", () => {
		const b = utils.attachNoViewportDefault(new FakeBrowser());
		b.newPage({ locale: "en-US" });
		expect(b.calls).toEqual([{ locale: "en-US", viewport: null }]);
	});
});

describe("test_humanize", () => {
	let captured: Record<string, any> = {};
	beforeEach(() => {
		isolateLaunch();
		deps.getEnvVars = (config) => {
			captured = { ...config };
			return {};
		};
	});

	const launchHumanize = (humanize: boolean | number) =>
		launch({ humanize, block_webgl: true, i_know_what_im_doing: true }).then(
			() => captured,
		);

	it("humanize: true sets no duration", async () => {
		const config = await launchHumanize(true);
		expect(config.humanize).toBe(true);
		expect("humanize:maxTime" in config).toBe(false);
	});

	it.each([
		1, 5, 1.25,
	])("a duration (%s) is encoded as a double", async (duration) => {
		const config = await launchHumanize(duration);
		expect(config.humanize).toBe(true);
		expect(config["humanize:maxTime"]).toBeInstanceOf(PyFloat);
		expect(Number(config["humanize:maxTime"])).toBe(duration);
		// ...and serialized with a floating-point representation.
		expect(utils.configJson({ t: config["humanize:maxTime"] })).toBe(
			`{"t":${Number.isInteger(duration) ? `${duration}.0` : duration}}`,
		);
	});
});

describe("test_executable_path_bundle", () => {
	it("reads the fontconfig from the supplied bundle", () => {
		deps.getPath = (() => {
			throw new Error(
				"resolved against the managed install despite executable_path",
			);
		}) as any;
		deps.osName = () => "lin";
		const env = utils.getEnvVars({}, "lin", BUNDLE_EXE);
		const generated = String(env.FONTCONFIG_FILE);
		expect(fs.existsSync(generated)).toBe(true);
		// The bundled conf's cwd-relative <dir> is rewritten to this bundle's fonts.
		expect(fs.readFileSync(generated, "utf-8")).toContain(
			path.join(BUNDLE, "fonts"),
		);
	});

	it("uses the managed install when no path is given", () => {
		const calls: string[] = [];
		deps.osName = () => "lin";
		deps.getPath = ((file: string) => {
			calls.push(file);
			return "/nonexistent";
		}) as any;
		expect(() => utils.getEnvVars({}, "lin")).toThrow();
		expect(calls.length).toBeGreaterThan(0);
	});
});

describe("test_executable_path_version_warning", () => {
	const bundle = (build: string) => {
		const dir = path.join(SCRATCH, `bundle-${build}`);
		fs.mkdirSync(dir, { recursive: true });
		fs.writeFileSync(
			path.join(dir, "version.json"),
			JSON.stringify({ version: "152.0.4", build }),
		);
		return path.join(dir, "camoufox-bin");
	};
	beforeEach(() => {
		deps.effectiveVersionMin = () => new Version("beta.30");
	});
	const runtimeWarnings = async (exe: string | null) =>
		(
			await warnings.recordWarnings(() =>
				utils.warnIfExecutablePredatesPlaywright(exe),
			)
		).warnings.filter((w) => w.category === "RuntimeWarning");

	it("warns when the supplied build is too old, naming the symptom", async () => {
		const caught = await runtimeWarnings(bundle("beta.29"));
		expect(caught).toHaveLength(1);
		expect(caught[0].message).toMatch(/beta\.29.*beta\.30/);
		expect(caught[0].message).toContain("Browser.setDefaultViewport");
	});

	it.each([
		"beta.30",
		"beta.31",
	])("is silent when the build (%s) is new enough", async (build) => {
		expect(await runtimeWarnings(bundle(build))).toEqual([]);
	});

	it("is silent for a custom build with no version.json", async () => {
		fs.mkdirSync(path.join(SCRATCH, "dist"), { recursive: true });
		expect(
			await runtimeWarnings(path.join(SCRATCH, "dist", "camoufox-bin")),
		).toEqual([]);
	});

	it("is silent when no executable path was given", async () => {
		expect(await runtimeWarnings(null)).toEqual([]);
	});
});

describe("test_voices (launch half)", () => {
	beforeEach(() => stubHost());
	const cfgOptions = (extra: Record<string, any> = {}) => ({
		headless: true,
		i_know_what_im_doing: true,
		executable_path: BUNDLE_EXE,
		os: "macos",
		fingerprint_preset: fingerprints.getRandomPreset("macos", "152"),
		...extra,
	});
	const cfg = async (extra: Record<string, any> = {}) =>
		configOf(await launch(cfgOptions(extra)));

	it("pins the block flag by default", async () => {
		expect((await cfg())["voices:blockIfNotDefined"]).toBe(true);
	});

	it("lets the caller override the block flag", async () => {
		expect(
			(await cfg({ config: { "voices:blockIfNotDefined": false } }))[
				"voices:blockIfNotDefined"
			],
		).toBe(false);
	});

	it("fails closed when voice generation fails", async () => {
		deps.generateRandomVoiceSubset = () => {
			throw new OSError("voice-manifests.json unreadable");
		};
		const { config, warned } = await launchWarning(
			cfgOptions(),
			"FallbackWarning",
			REPORT,
		);
		expect(warned).toBe(true);
		// An empty list plus the block flag means "no voices" -- never "all of
		// the host's".
		expect(config.voices).toEqual([]);
		expect(config["voices:blockIfNotDefined"]).toBe(true);
	});

	it.each([
		[["Alex:en-US:local"]],
		[[{ name: "Alex", lang: "en-US" }]],
		["Alex"],
	])("validateVoices rejects %j", (value) => {
		expect(() => utils.validateVoices(value)).toThrow(InvalidPropertyType);
	});

	it.each([
		[[]],
		[
			[
				{
					lang: "en-US",
					name: "Alex",
					voiceUri: "urn:moz-tts:osx:alex",
					isDefault: true,
					isLocalService: true,
				},
			],
		],
	])("validateVoices accepts %j", (value) => {
		expect(() => utils.validateVoices(value)).not.toThrow();
	});
});

describe.skipIf(!modelReady)(
	"test_launch_geometry / test_identity_salt (fpgen draws)",
	() => {
		beforeEach(() => stubHost());

		const launchConfig = async (extra: Record<string, any>) =>
			configOf(
				await launch({
					os: "windows",
					i_know_what_im_doing: true,
					executable_path: BUNDLE_EXE,
					...extra,
				}),
			);
		const withDisplay = (
			screen: { maxWidth: number; maxHeight: number } | null,
		) => {
			deps.hasDisplay = () => true;
			deps.getScreenCons = () =>
				screen ? new fingerprints.Screen(screen) : null;
		};

		it("a virtual display is not a screen: the fingerprint is not shrunk to the 1x1 Xvfb", async () => {
			withDisplay({ maxWidth: 1, maxHeight: 1 });
			const config = await launchConfig({
				headless: false,
				virtual_display: ":99",
			});
			expect(config["screen.width"]).toBeGreaterThan(1);
			expect(config["screen.height"]).toBeGreaterThan(1);
			expect(config["window.outerWidth"]).toBeGreaterThan(1);
			for (const [key, value] of Object.entries(config)) {
				if (key.startsWith("screen.") || key.startsWith("window.outer")) {
					expect(value as number, key).toBeGreaterThanOrEqual(0);
				}
			}
		});

		it("headful generated geometry never exceeds the display (15 draws)", async () => {
			withDisplay({ maxWidth: 1280, maxHeight: 720 });
			for (let attempt = 0; attempt < 15; attempt++) {
				const config = await launchConfig({ headless: false });
				for (const [key, bound] of [
					["screen.width", 1280],
					["screen.height", 720],
					["window.outerWidth", 1280],
					["window.outerHeight", 720],
				] as const) {
					expect(config[key], key).toBeLessThanOrEqual(bound);
				}
				expect(config["screen.availWidth"]).toBeLessThanOrEqual(
					config["screen.width"],
				);
				expect(config["screen.availHeight"]).toBeLessThan(
					config["screen.height"],
				);
				expect(config["window.outerWidth"]).toBeLessThanOrEqual(
					config["screen.availWidth"],
				);
				expect(config["window.outerHeight"]).toBeLessThanOrEqual(
					config["screen.availHeight"],
				);
			}
		});

		it("an unprobeable display is not clamped", async () => {
			withDisplay(null);
			let clamped = false;
			deps.clampScreenToDisplay = () => {
				clamped = true;
			};
			await launchConfig({ headless: false });
			expect(clamped).toBe(false);
		});

		it("never spoofs the inner window dimensions", async () => {
			for (const osName of ["linux", "windows", "macos"]) {
				for (let i = 0; i < 5; i++) {
					const config = await launchConfig({ os: osName });
					expect("window.innerWidth" in config, osName).toBe(false);
					expect("window.innerHeight" in config, osName).toBe(false);
				}
			}
		});

		it("unpinned launches never share noise seeds", async () => {
			const seeds = new Set<number>();
			for (let i = 0; i < 40; i++) {
				seeds.add(
					(await launchConfig({ os: "linux", headless: true }))["audio:seed"],
				);
			}
			expect(seeds.size).toBe(40);
		});

		it("a fixed fingerprint reproduces every draw", async () => {
			const fp = fingerprints.generateFingerprint({ os: "linux" });
			const drawn = (c: Record<string, any>) =>
				JSON.stringify(
					["audio:seed", "fonts", "voices", "webGl:renderer"].map((k) => c[k]),
				);
			const first = await launchConfig({ os: "linux", fingerprint: fp });
			const second = await launchConfig({ os: "linux", fingerprint: fp });
			expect(drawn(first)).toBe(drawn(second));
		});

		it("a fixed preset reproduces the noise seeds and fonts", async () => {
			const preset = fingerprints.getRandomPreset("windows", "150");
			const first = await launchConfig({ fingerprint_preset: preset });
			const second = await launchConfig({ fingerprint_preset: preset });
			expect(first["audio:seed"]).toBe(second["audio:seed"]);
			expect(first.fonts).toEqual(second.fonts);
		});

		it.each([
			undefined,
			false,
		])("fingerprint_preset=%s never draws a preset", async (off) => {
			// False used to be checked with `!= null`, so it drew a random preset.
			deps.getRandomPreset = () => {
				throw new Error("preset drawn");
			};
			await launchConfig({ os: "linux", fingerprint_preset: off });
		});

		it("generates no glyph-spacing seed", async () => {
			// The noise was itself a fingerprint; the browser no longer has it.
			expect("fonts:spacing_seed" in (await launchConfig({}))).toBe(false);
			const context = fingerprints.generateContextFingerprint({ os: "linux" });
			expect("fonts:spacing_seed" in context.config).toBe(false);
			expect(context.init_script).not.toContain("setFontSpacingSeed");
		});

		it("config_overrides reach the config and the init script", () => {
			const context = fingerprints.generateContextFingerprint({
				os: "linux",
				config_overrides: { "audio:seed": 7 },
			});
			expect(context.config["audio:seed"]).toBe(7);
			expect(context.init_script).toContain("setAudioFingerprintSeed(7)");
		});

		it("a failed font draw warns and uses the OS's font list", async () => {
			deps.generateRandomFontSubset = () => {
				throw new OSError("font-bases.json missing");
			};
			const { config, warned } = await launchWarning(
				{
					os: "windows",
					i_know_what_im_doing: true,
					executable_path: BUNDLE_EXE,
				},
				"FallbackWarning",
				"OSError: font-bases.json missing",
			);
			expect(warned).toBe(true);
			expect(config.fonts.length).toBeGreaterThan(0);
		});

		it("a preset keeps its own GPU (test_webgl.py)", async () => {
			const preset = fingerprints.loadPresets("152")?.presets.linux[0];
			const config = await launchConfig({
				os: "linux",
				fingerprint_preset: preset,
			});
			expect([config["webGl:vendor"], config["webGl:renderer"]]).toEqual([
				preset.webgl.unmaskedVendor,
				preset.webgl.unmaskedRenderer,
			]);
		});

		it("a preset GPU is checked against the host core count (test_coherence.py)", async () => {
			// The launch replaces the preset's cores with the host's after the
			// preset's GPU is read: the GPU has to fit the count that ships.
			const base = fingerprints.loadPresets("152")?.presets.macos[0];
			const preset = {
				...base,
				navigator: { ...base.navigator, hardwareConcurrency: 8 },
				screen: {
					...base.screen,
					width: 1440,
					height: 900,
					availWidth: 1440,
					availHeight: 875,
				},
				webgl: {
					...base.webgl,
					unmaskedVendor: "Intel Inc.",
					unmaskedRenderer: "Intel(R) HD Graphics 400, or similar",
				},
			};
			deps.fixHardwareConcurrency = (config, canPin) =>
				fingerprints.fixHardwareConcurrency(config, canPin, { cpuCount: 20 });
			const config = await launchConfig({
				os: "macos",
				fingerprint_preset: preset,
			});
			expect(config["navigator.hardwareConcurrency"]).toBe(20);
			expect(config["webGl:renderer"]).not.toContain("Intel");
		});

		it("a preset GPU fpgen has never seen raises", async () => {
			const preset = {
				...fingerprints.loadPresets("152")?.presets.windows[0],
				webgl: {
					unmaskedVendor: "Google Inc. (Acme)",
					unmaskedRenderer:
						"ANGLE (Acme, Acme GPU 9000 Direct3D11 vs_5_0 ps_5_0)",
				},
			};
			await expect(
				launchConfig({ os: "windows", fingerprint_preset: preset }),
			).rejects.toThrow(/Acme GPU 9000/);
		});

		it("an unknown webgl_config raises", async () => {
			await expect(
				launchConfig({
					os: "windows",
					webgl_config: ["Apple", "Apple M1, or similar"],
				}),
			).rejects.toThrow(/No recorded WebGL data/);
		});

		it("a device without WebGL2 turns WebGL2 off", async () => {
			const options = await launch({
				os: "windows",
				headless: true,
				i_know_what_im_doing: true,
				executable_path: BUNDLE_EXE,
				webgl_config: [
					"Google Inc. (Microsoft)",
					"ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0), or similar",
				],
			});
			expect(options.firefoxUserPrefs["webgl.enable-webgl2"]).toBe(false);
		});

		it("instantAnimations warns that it is detectable", async () => {
			const { warned } = await launchWarning(
				{
					os: "windows",
					executable_path: BUNDLE_EXE,
					config: { instantAnimations: true },
					i_know_what_im_doing: false,
				},
				"LeakWarning",
				"getComputedTiming",
			);
			expect(warned).toBe(true);
		});

		it("is_mobile warns that Camoufox is desktop-only", async () => {
			const { warned } = await launchWarning(
				{
					os: "windows",
					executable_path: BUNDLE_EXE,
					is_mobile: true,
					i_know_what_im_doing: false,
				},
				"LeakWarning",
				"built for desktops",
			);
			expect(warned).toBe(true);
		});

		it("keeps the caller's seeds", async () => {
			const config = await launchConfig({
				os: "linux",
				config: { "audio:seed": 9 },
			});
			expect(config["audio:seed"]).toBe(9);
		});

		it("a Windows fr-FR identity has French voices", async () => {
			for (let i = 0; i < 5; i++) {
				const config = await launchConfig({ os: "windows", locale: "fr-FR" });
				expect(
					new Set(config.voices.map((v: any) => v.lang)).has("fr-FR"),
				).toBe(true);
			}
		});

		it.each([
			"windows",
			"macos",
			"linux",
		])("every bundled %s preset launches with its own GPU", async (osName) => {
			const presets = fingerprints.loadPresets("150")?.presets[osName] ?? [];
			expect(presets.length).toBeGreaterThan(0);
			for (const [i, preset] of presets.entries()) {
				const config = await launchConfig({
					os: osName,
					fingerprint_preset: preset,
				});
				expect(config["webGl:parameters"], `${osName} ${i}`).toBeTruthy();
				expect(config["webGl:renderer"], `${osName} ${i}`).toBe(
					preset.webgl.unmaskedRenderer,
				);
			}
		}, 120_000);
	},
);

describe("cpu_affinity", () => {
	it("picks adjacent cores from a random start (test_identity_salt.TestAffinityPick)", () => {
		const cores = Array.from({ length: 16 }, (_, i) => i);
		const seen = new Set<string>();
		for (let n = 0; n < 200; n++) {
			const picked = cpuAffinity.pick(cores, 4);
			expect(picked).toHaveLength(4);
			expect(picked.every((c) => cores.includes(c))).toBe(true);
			expect(
				picked.some((s) =>
					[0, 1, 2, 3].every((i) => picked.includes((s + i) % 16)),
				),
			).toBe(true);
			seen.add(picked.join(","));
		}
		expect(seen.size).toBeGreaterThan(4);
	});

	it("parses a Linux cpu list", () => {
		expect(cpuAffinity.parseCpuList("0-3,8,10-11\n")).toEqual([
			0, 1, 2, 3, 8, 10, 11,
		]);
	});

	it("round-trips a Windows affinity mask", () => {
		expect(
			cpuAffinity.maskToCores(cpuAffinity.coresToMask([0, 2, 5, 63])),
		).toEqual([0, 2, 5, 63]);
	});

	it("pins only to a count the host can honour", () => {
		const options = (hc: number) => ({
			env: utils.getEnvVars(
				{ "navigator.hardwareConcurrency": hc },
				"win",
				BUNDLE_EXE,
			),
		});
		const cores = cpuAffinity.hostCores() ?? [];
		if (!cpuAffinity.supported() || cores.length < 3) return;
		expect(utils.pinnedCoreCount(options(2))).toBe(2);
		expect(utils.pinnedCoreCount(options(cores.length))).toBeNull();
		expect(utils.pinnedCoreCount({})).toBeNull();
	});

	it.runIf(process.platform === "linux")(
		"pins and restores this process on Linux",
		() => {
			if (!cpuAffinity.supported()) return;
			const before = cpuAffinity.hostCores() ?? [];
			if (before.length < 2) return;
			const previous = cpuAffinity.pin(process.pid, 1);
			try {
				expect(previous).toEqual(before);
				expect(cpuAffinity.hostCores()).toHaveLength(1);
			} finally {
				cpuAffinity.restore(process.pid, previous);
			}
			expect(cpuAffinity.hostCores()).toEqual(before);
		},
	);

	it.runIf(process.platform === "linux")(
		"a concurrent launch sees the host's cores, not another launch's pin",
		() => {
			if (!cpuAffinity.supported()) return;
			const host = cpuAffinity.hostCores() ?? [];
			if (host.length < 3) return;
			const options = utils.getEnvVars(
				{ "navigator.hardwareConcurrency": 2 },
				"win",
				BUNDLE_EXE,
			);
			const previous = cpuAffinity.pin(process.pid, 1);
			try {
				expect(cpuAffinity.hostCores()).toHaveLength(1);
				expect(cpuAffinity.hostCoreCount()).toBe(host.length);
				expect(fingerprints.hostCpuCount()).toBe(host.length);
				expect(utils.pinnedCoreCount({ env: options })).toBe(2);
			} finally {
				cpuAffinity.restore(process.pid, previous);
			}
		},
	);

	it("an unpinned launch waits for a pinned one to spawn and restore", async () => {
		const order: string[] = [];
		const pinned = cpuAffinity.withPinLock(async () => {
			await new Promise((r) => setTimeout(r, 30));
			order.push("pinned launch restored");
		});
		const unpinned = cpuAffinity.withUnpinnedLaunch(async () => {
			order.push("unpinned launch spawned");
		});
		await Promise.all([pinned, unpinned]);
		expect(order).toEqual([
			"pinned launch restored",
			"unpinned launch spawned",
		]);
	});
});
