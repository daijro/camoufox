/**
 * fingerprint_options: the noise Camoufox adds on top of an identity. Twin of
 * python/tests/test_fingerprint_options.py.
 *
 * `{audio: {noise: false}}` renders Web Audio as stock Firefox does,
 * `{audio: {seed: N}}` fixes the audio seed, and `{canvas: {randomize}}` sets
 * canvas randomization. Without an entry the seed follows the identity (#442/
 * #765). The older canvas_noise and config `audio:seed` still work and warn.
 * NewContext contexts take the audio entry; without one they follow the browser.
 */

import { afterAll, afterEach, beforeEach, describe, expect, it } from "vitest";
import {
	BUNDLE_EXE,
	configOf,
	fingerprints,
	HOME,
	quietly,
	restoreDeps,
	SCRATCH,
	stubHost,
	utils,
	warnings,
} from "./launch-host.js";

const fs = await import("node:fs");
const { InvalidFingerprintOptions } = await import("../src/exceptions.js");
const { hasCanvasPlaceholder } = await import("../src/host_rendering.js");
const { NewBrowser, NewContext } = await import("../src/sync_api.js");
const { MODEL } = await import("./fpgen-setup.js");

afterEach(() => restoreDeps());
afterAll(() => fs.rmSync(SCRATCH, { recursive: true, force: true }));

const AUDIO_OFF = { audio: { noise: false } };

const optionsFor = (opts: Record<string, any> = {}) =>
	quietly(() =>
		utils.launchOptions({
			env: { HOME },
			os: "linux",
			headless: true,
			i_know_what_im_doing: true,
			executable_path: BUNDLE_EXE,
			...opts,
		}),
	);

const seedSent = async (opts: Record<string, any> = {}) =>
	configOf(await optionsFor(opts))["audio:seed"];

/** The launch's options and the warnings of `category` it emitted. */
async function warned(opts: Record<string, any>, category: string) {
	const {
		result,
		error,
		warnings: caught,
	} = await warnings.recordWarnings(() =>
		utils.launchOptions({
			env: { HOME },
			os: "linux",
			headless: true,
			i_know_what_im_doing: true,
			executable_path: BUNDLE_EXE,
			...opts,
		}),
	);
	return {
		result: result as Record<string, any>,
		error,
		messages: caught
			.filter((w) => w.category === category)
			.map((w) => w.message),
	};
}

describe.skipIf(!MODEL.ok)("fingerprint_options", () => {
	beforeEach(() => stubHost());
	const preset = () => fingerprints.getRandomPreset("linux", "150");

	describe("launch audio", () => {
		it("the default seed follows the identity", async () => {
			const p = preset();
			const seed = await seedSent({ fingerprint_preset: p });
			expect(seed).not.toBe(0);
			expect(await seedSent({ fingerprint_preset: p })).toBe(seed);
		});

		it.each([
			{},
			{ noise: true },
		])("an entry without a choice (%j) is the default", async (audio) => {
			const p = preset();
			expect(
				await seedSent({
					fingerprint_preset: p,
					fingerprint_options: { audio },
				}),
			).toBe(await seedSent({ fingerprint_preset: p }));
		});

		it("noise off sends the browser's no-noise seed, over a preset's", async () => {
			expect(await seedSent({ fingerprint_options: AUDIO_OFF })).toBe(0);
			expect(
				await seedSent({
					os: "windows",
					fingerprint_preset: fingerprints.getRandomPreset("windows", "150"),
					fingerprint_options: AUDIO_OFF,
				}),
			).toBe(0);
		});

		it.each([
			1, 1000433, 0xffffffff,
		])("a fixed seed %d is sent", async (seed) => {
			expect(await seedSent({ fingerprint_options: { audio: { seed } } })).toBe(
				seed,
			);
			expect(
				await seedSent({
					fingerprint_options: { audio: { seed, noise: true } },
				}),
			).toBe(seed);
		});
	});

	describe("validation", () => {
		it.each([
			"fonts",
			"glyphs",
			"webgl",
		])("%s, a surface Camoufox does not noise, throws", async (surface) => {
			await expect(
				optionsFor({ fingerprint_options: { [surface]: { noise: false } } }),
			).rejects.toThrow(/no-glyph-spacing-noise/);
		});

		it.each([
			{ audio: { off: true } },
			{ canvas: { seed: 3 } },
			{ audio: false },
			{ canvas: true },
			{ audio: { noise: 0 } },
			{ canvas: { randomize: "yes" } },
			["audio"],
		])("an unknown key or shape %j throws", async (options) => {
			await expect(
				optionsFor({ fingerprint_options: options }),
			).rejects.toBeInstanceOf(InvalidFingerprintOptions);
		});

		it.each([
			0,
			-1,
			0x100000000,
			true,
			"5",
			1.5,
			null,
		])("a seed of %j throws", async (seed) => {
			await expect(
				optionsFor({ fingerprint_options: { audio: { seed } } }),
			).rejects.toThrow(/1 to 4294967295/);
		});

		it("noise off with a seed throws", async () => {
			await expect(
				optionsFor({
					fingerprint_options: { audio: { noise: false, seed: 5 } },
				}),
			).rejects.toThrow(/Pass one of them/);
		});
	});

	describe("old forms", () => {
		it("an audio:seed in config still works and warns", async () => {
			for (const seed of [9, 0]) {
				const { result, messages } = await warned(
					{ config: { "audio:seed": seed } },
					"FutureWarning",
				);
				expect(configOf(result)["audio:seed"]).toBe(seed);
				expect(messages.join()).toContain('fingerprint_options={"audio"');
			}
		});

		it.each([
			{ noise: false },
			{ seed: 9 },
			{},
		])("an audio:seed in config with an audio entry %j throws", async (audio) => {
			await expect(
				optionsFor({
					config: { "audio:seed": 9 },
					fingerprint_options: { audio },
				}),
			).rejects.toThrow(/both set the audio noise/);
		});

		it.each([
			true,
			false,
		])("canvas_noise %s still works and warns", async (randomize) => {
			const { result, messages } = await warned(
				{ os: "windows", canvas_noise: randomize },
				"FutureWarning",
			);
			expect(messages.join()).toContain('fingerprint_options={"canvas"');
			const fresh = await optionsFor({
				os: "windows",
				fingerprint_options: { canvas: { randomize } },
			});
			expect(hasCanvasPlaceholder(result.firefoxUserPrefs)).toBe(randomize);
			expect(hasCanvasPlaceholder(fresh.firefoxUserPrefs)).toBe(randomize);
		});

		it("canvas_noise with a canvas entry throws", async () => {
			await expect(
				optionsFor({
					canvas_noise: true,
					fingerprint_options: { canvas: { randomize: true } },
				}),
			).rejects.toThrow(/both set canvas randomization/);
		});

		it("the new forms do not warn", async () => {
			const { messages } = await warned(
				{
					fingerprint_options: {
						audio: { seed: 4 },
						canvas: { randomize: false },
					},
				},
				"FutureWarning",
			);
			expect(messages).toEqual([]);
		});
	});

	it("without a canvas entry another OS is randomized", async () => {
		const options = await optionsFor({ os: "windows" });
		expect(hasCanvasPlaceholder(options.firefoxUserPrefs)).toBe(true);
	});

	/** A NewBrowser browser (Playwright faked) launched with these options;
	 * `contexts` records each context's init script. */
	async function browserLaunchedWith(
		opts: Record<string, any> = {},
		probeAnswer = true,
	) {
		const contexts: { script: string; probe: boolean }[] = [];
		const browser: any = {
			version: () => "150.0.2",
			newContext: async () => {
				const context: any = {
					script: "",
					probe: false,
					addInitScript: async (s: string) => {
						context.script = s;
						context.probe = s === utils.AUDIO_OFF_PROBE;
					},
					newPage: async () => ({ evaluate: async () => probeAnswer }),
					close: async () => undefined,
				};
				contexts.push(context);
				return context;
			},
		};
		const firefox: any = { launch: async () => browser };
		await quietly(() =>
			NewBrowser(firefox, {
				os: "linux",
				headless: true,
				i_know_what_im_doing: true,
				executable_path: BUNDLE_EXE,
				...opts,
			}),
		);
		return { browser, contexts };
	}

	function audioCalls(script: string): [number | null, boolean] {
		const seed = /setAudioFingerprintSeed\((\d+)\)/.exec(script);
		return [
			seed ? Number(seed[1]) : null,
			script.includes("w.setAudioFingerprintNoise(false)"),
		];
	}

	const lastScript = (contexts: { script: string }[]) =>
		contexts[contexts.length - 1].script;

	describe("contexts", () => {
		it("NewBrowser records the seed the launch sent", async () => {
			expect(
				(await browserLaunchedWith({ fingerprint_options: AUDIO_OFF })).browser
					._camoufoxAudioSeed,
			).toBe(0);
			expect(
				(
					await browserLaunchedWith({
						fingerprint_options: { audio: { seed: 77 } },
					})
				).browser._camoufoxAudioSeed,
			).toBe(77);
			const built = await optionsFor({ config: { "audio:seed": 0 } });
			expect(
				(await browserLaunchedWith({ from_options: built })).browser
					._camoufoxAudioSeed,
			).toBe(0);
		});

		it("NewBrowser hands the canvas choice to its contexts, and both forms throw", async () => {
			await expect(
				browserLaunchedWith({
					canvas_noise: true,
					fingerprint_options: { canvas: { randomize: true } },
				}),
			).rejects.toBeInstanceOf(InvalidFingerprintOptions);
			const { browser } = await browserLaunchedWith({
				fingerprint_options: { canvas: { randomize: false } },
			});
			expect(browser._camoufoxHostIdentity).toBeNull();
		});

		it("a context of a noised browser draws its own seed", async () => {
			const { browser, contexts } = await browserLaunchedWith();
			await NewContext(browser, { os: "linux" });
			const [seed, off] = audioCalls(lastScript(contexts));
			expect([null, 0, browser._camoufoxAudioSeed]).not.toContain(seed);
			expect(off).toBe(false);
		});

		it("a context does not take the browser's fixed seed", async () => {
			const { browser, contexts } = await browserLaunchedWith({
				fingerprint_options: { audio: { seed: 1000433 } },
			});
			const seeds = new Set<number | null>();
			for (let i = 0; i < 3; i++) {
				await NewContext(browser, { os: "linux" });
				seeds.add(audioCalls(lastScript(contexts))[0]);
			}
			expect(seeds.size).toBe(3);
			expect(seeds.has(1000433)).toBe(false);
		});

		it("a context of a browser without noise has none, and needs no probe", async () => {
			const { browser, contexts } = await browserLaunchedWith({
				fingerprint_options: AUDIO_OFF,
			});
			await NewContext(browser, { os: "linux" });
			expect(audioCalls(lastScript(contexts))).toEqual([null, true]);
			await NewContext(browser, {
				os: "linux",
				fingerprint_options: AUDIO_OFF,
			});
			expect(audioCalls(lastScript(contexts))).toEqual([null, true]);
			expect(contexts.length).toBe(2);
		});

		it.each([
			{},
			{ fingerprint_options: AUDIO_OFF },
		])("a context of a browser launched with %j takes its own seed", async (launch) => {
			const { browser, contexts } = await browserLaunchedWith(launch);
			await NewContext(browser, {
				os: "linux",
				fingerprint_options: { audio: { seed: 31 } },
			});
			expect(audioCalls(lastScript(contexts))).toEqual([31, false]);
		});

		it("a context with noise on draws a seed on a browser without noise", async () => {
			const { browser, contexts } = await browserLaunchedWith({
				fingerprint_options: AUDIO_OFF,
			});
			await NewContext(browser, {
				os: "linux",
				fingerprint_options: { audio: { noise: true } },
			});
			const [seed, off] = audioCalls(lastScript(contexts));
			expect([null, 0]).not.toContain(seed);
			expect(off).toBe(false);
		});

		it("a context turns its noise off on a noised browser, asking the browser once", async () => {
			const { browser, contexts } = await browserLaunchedWith();
			for (let i = 0; i < 2; i++) {
				await NewContext(browser, {
					os: "linux",
					fingerprint_options: AUDIO_OFF,
				});
				expect(audioCalls(lastScript(contexts))).toEqual([null, true]);
			}
			expect(contexts.map((c) => c.probe)).toEqual([true, false, false]);
		});

		it("a build without the setter throws instead of staying noised", async () => {
			const { browser, contexts } = await browserLaunchedWith({}, false);
			for (let i = 0; i < 2; i++) {
				await expect(
					NewContext(browser, { os: "linux", fingerprint_options: AUDIO_OFF }),
				).rejects.toThrow(/setAudioFingerprintNoise/);
			}
			expect(contexts.length).toBe(1);
		});

		it("canvas in a context throws", async () => {
			const { browser } = await browserLaunchedWith();
			await expect(
				NewContext(browser, {
					fingerprint_options: { canvas: { randomize: true } },
				}),
			).rejects.toThrow(/belongs to the browser/);
		});

		it.each([
			{ fonts: {} },
			{ audio: { seed: 0 } },
			{ audio: { noise: false, seed: 3 } },
		])("an invalid context entry %j throws", async (options) => {
			const { browser } = await browserLaunchedWith();
			await expect(
				NewContext(browser, { fingerprint_options: options as any }),
			).rejects.toBeInstanceOf(InvalidFingerprintOptions);
		});
	});
});

describe("init script", () => {
	it("seed 0 turns the noise off rather than inheriting the launch seed", () => {
		const script = fingerprints.buildInitScript({ audioFingerprintSeed: 0 });
		expect(script).toContain(
			'if (typeof w.setAudioFingerprintNoise === "function") w.setAudioFingerprintNoise(false);',
		);
		expect(script).not.toContain("setAudioFingerprintSeed");
	});

	it("a seed is set as before", () => {
		const script = fingerprints.buildInitScript({ audioFingerprintSeed: 5 });
		expect(script).toContain("w.setAudioFingerprintSeed(5);");
		expect(script).not.toContain("setAudioFingerprintNoise");
	});
});
