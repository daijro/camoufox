/**
 * End-to-end: launch a real Camoufox build through the TypeScript API and
 * check what a page actually sees.
 *
 * Opt-in -- it needs a browser binary:
 *
 *   CAMOUFOX_E2E=1 CAMOUFOX_EXECUTABLE=/path/to/camoufox-bin pnpm test tests/e2e.test.ts
 *
 * Two kinds of assertion, deliberately kept apart:
 *
 *  - PARITY, always enforced: for each fixed identity it launches headless, as a
 *    persistent context, through launchServer() and through NewContext(), runs
 *    tests/fixtures/e2e/probe.js on a local page, then launches the PYTHON
 *    camoufox on the same binary with the same identity
 *    (scripts/e2e/python_probe.py, run with $CAMOUFOX_E2E_PYTHON or the repo's
 *    .venv) and requires the same CAMOU_CONFIG and the same probe result. This is
 *    the claim this package makes, and it holds on any binary.
 *
 *  - THE BROWSER HONOURS THE CONFIG: navigator/screen/window/fonts/timezone/
 *    voices/WebGL on the page equal what the launcher sent. That is the
 *    browser's half of the contract, so it is only asserted on a binary that
 *    knows every key the launcher sets (its properties.json lists them). An
 *    older binary -- the published release, on a driver-only pull request, while
 *    the launcher is ahead of it -- ignores the keys it does not know, exactly
 *    as pythonlib's "Skipping unknown patch" says, and those tests skip naming
 *    the missing keys rather than failing on the skew.
 */
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import AdmZip from "adm-zip";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PYTHON as GOLDEN_PYTHON } from "./golden-setup.js";
import { prerequisite } from "./prereq.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..", "..");
const EXECUTABLE = process.env.CAMOUFOX_EXECUTABLE ?? "";
const ENABLED = process.env.CAMOUFOX_E2E === "1" && Boolean(EXECUTABLE);
const PYTHON = process.env.CAMOUFOX_E2E_PYTHON ?? GOLDEN_PYTHON;
const PROBE = fs.readFileSync(
	path.join(HERE, "fixtures", "e2e", "probe.js"),
	"utf-8",
);
const INPUTS = JSON.parse(
	fs.readFileSync(
		path.join(HERE, "fixtures", "launch", "inputs.json"),
		"utf-8",
	),
);

/** The fixed identities: an fpgen fingerprint and a cross-OS preset. */
const IDENTITIES: Record<string, Record<string, any>> = {
	fpgen_linux_de: {
		fingerprint: INPUTS.fingerprints.linux,
		os: "linux",
		locale: "de-DE",
		config: { timezone: "Asia/Tokyo" },
	},
	preset_windows_fr: {
		fingerprint_preset: INPUTS.presets.windows,
		locale: "fr-FR",
		config: { timezone: "Europe/Paris" },
	},
};

/** Config keys the binary under test does not know (see the header). */
function unknownToBinary(config: Record<string, any>): string[] {
	const dir = path.dirname(EXECUTABLE);
	const candidates = [
		path.join(dir, "properties.json"),
		path.join(dir, "..", "Resources", "properties.json"), // macOS bundle
	];
	const file = candidates.find((f) => fs.existsSync(f));
	if (!file) return ["<no properties.json beside the binary>"];
	const known = new Set(
		JSON.parse(fs.readFileSync(file, "utf-8")).map((p: any) => p.property),
	);
	return Object.keys(config).filter((k) => !known.has(k));
}

/**
 * The locales the binary under test packages (res/multilocale.txt): loose in
 * an unpackaged dist/bin, inside omni.ja in a packaged build. A spoofed locale
 * the binary does not package falls back to en-US -- scripts/package.py adds the
 * langpacks, so a packaged release has them and CI's unpackaged dist/bin does
 * not. null when it cannot be read.
 */
function packagedLocales(): string[] | null {
	const dir = path.dirname(EXECUTABLE);
	try {
		const loose = path.join(dir, "res", "multilocale.txt");
		const text = fs.existsSync(loose)
			? fs.readFileSync(loose, "utf-8")
			: new AdmZip(path.join(dir, "omni.ja"))
					.getEntry("res/multilocale.txt")
					?.getData()
					.toString("utf-8");
		return text
			? text
					.split(",")
					.map((l) => l.trim())
					.filter(Boolean)
			: null;
	} catch {
		return null;
	}
}

let server: http.Server;
let url = "";
/** The User-Agent header of the last request the probe page served. */
let lastRequestUserAgent = "";

beforeAll(async () => {
	if (!ENABLED) return;
	server = http.createServer((req, res) => {
		lastRequestUserAgent = req.headers["user-agent"] ?? "";
		res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
		res.end(
			"<!doctype html><html><head><title>probe</title></head><body>probe</body></html>",
		);
	});
	await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
	url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/`;
});

afterAll(async () => {
	if (server) await new Promise((resolve) => server.close(resolve));
});

function configOf(options: Record<string, any>): Record<string, any> {
	const env = options.env as Record<string, string>;
	return JSON.parse(
		Object.keys(env)
			.filter((k) => k.startsWith("CAMOU_CONFIG_"))
			.sort((a, b) => Number(a.split("_").pop()) - Number(b.split("_").pop()))
			.map((k) => env[k])
			.join(""),
	);
}

function kwargsFor(identity: string): Record<string, any> {
	return {
		...structuredClone(IDENTITIES[identity]),
		executable_path: EXECUTABLE,
		headless: true,
		i_know_what_im_doing: true,
	};
}

/**
 * Give a headful page focus and wait until it has it. One bringToFront() on a
 * bare Xvfb, with no window manager, sometimes left the window unfocused, and
 * Firefox holds enumerateDevices() until the document has focus.
 */
async function focusPage(page: any): Promise<void> {
	for (let i = 0; i < 50; i++) {
		await page.bringToFront();
		if (await page.evaluate("document.hasFocus()")) return;
		await new Promise((r) => setTimeout(r, 200));
	}
	throw new Error("the headful page never got focus on Xvfb");
}

async function probePage(page: any): Promise<any> {
	await page.goto(url);
	// Python's evaluate() calls a function-source string; JS's evaluates it as
	// an expression, so call it explicitly.
	return page.evaluate(`(${PROBE})()`);
}

/**
 * Run the Python side. Asynchronously: the probe page is served from this
 * process, so blocking the event loop would hang Python's page.goto().
 */
function pythonProbe(
	mode: string,
	kwargs: Record<string, any>,
	extra: Record<string, any> = {},
): Promise<any> {
	return new Promise((resolve, reject) => {
		const child = spawn(
			PYTHON,
			[path.join(REPO, "typescript", "scripts", "e2e", "python_probe.py")],
			{
				stdio: ["pipe", "pipe", "pipe"],
			},
		);
		let stdout = "";
		let stderr = "";
		child.stdout.on("data", (d) => {
			stdout += d;
		});
		child.stderr.on("data", (d) => {
			stderr += d;
		});
		child.on("error", reject);
		child.on("close", (code) => {
			if (code !== 0) {
				reject(new Error(`python probe failed (${code}): ${stderr}`));
				return;
			}
			try {
				resolve(JSON.parse(stdout));
			} catch (err) {
				reject(
					new Error(
						`python probe printed non-JSON (${err}): ${stdout.slice(0, 500)}`,
					),
				);
			}
		});
		child.stdin.end(JSON.stringify({ mode, url, kwargs, ...extra }));
	});
}

/**
 * The probe minus the canvas hash. The canvas readback differs between two
 * launches of the SAME config -- measured with this build,
 * TS and Python alike -- so it is compared by its size only.
 */
/**
 * `promise`, or a rejection naming the step after `ms`. A hung launch otherwise
 * surfaces only as vitest's whole-test timeout, which says nothing about where.
 */
function step<T>(what: string, promise: Promise<T>, ms = 60_000): Promise<T> {
	let timer: NodeJS.Timeout | undefined;
	return Promise.race([
		promise,
		new Promise<never>((_, reject) => {
			timer = setTimeout(
				() => reject(new Error(`${what}: did not complete in ${ms / 1000} s`)),
				ms,
			);
		}),
	]).finally(() => clearTimeout(timer));
}

function stable(probe: any): any {
	const { canvasHash, ...rest } = probe;
	return { ...rest, canvasSize: String(canvasHash).split(":")[1] };
}

/** What the page must report for a config the launcher sent. */
function expectMatchesConfig(
	probe: any,
	config: Record<string, any>,
	headful = false,
) {
	expect(probe.navigator.userAgent).toBe(config["navigator.userAgent"]);
	expect(probe.navigator.platform).toBe(config["navigator.platform"]);
	if ("navigator.oscpu" in config)
		expect(probe.navigator.oscpu).toBe(config["navigator.oscpu"]);
	expect(probe.navigator.hardwareConcurrency).toBe(
		config["navigator.hardwareConcurrency"],
	);
	expect(probe.navigator.webdriver).toBe(false);
	// DNT / GPC follow stock Firefox unless the caller set them.
	expect(probe.navigator.doNotTrack).toBe("unspecified");
	expect(probe.navigator.globalPrivacyControl).toBe(false);
	for (const key of [
		"width",
		"height",
		"availWidth",
		"availHeight",
		"colorDepth",
	]) {
		if (`screen.${key}` in config)
			expect(probe.screen[key], `screen.${key}`).toBe(config[`screen.${key}`]);
	}
	for (const key of ["outerWidth", "outerHeight"]) {
		if (`window.${key}` in config)
			expect(probe.window[key], `window.${key}`).toBe(config[`window.${key}`]);
	}
	expect(probe.intl.timeZone).toBe(config.timezone);
	const lang = [config["locale:language"], config["locale:region"]].join("-");
	const packaged = packagedLocales();
	const hasLocale =
		packaged === null ||
		packaged.includes(lang) ||
		packaged.includes(config["locale:language"]);
	if (
		prerequisite(
			"packaged-locales",
			hasLocale,
			`the binary packages ${packaged?.join(",")}, not ${lang}`,
		)
	) {
		expect(probe.navigator.language).toBe(lang);
		expect(probe.intl.locale).toBe(lang);
	}
	// Fonts: every probed family the identity claims resolves; the others don't.
	const claimed = new Set<string>(config.fonts);
	for (const [family, present] of Object.entries(probe.fonts)) {
		if (!claimed.has(family)) expect(present, `${family} leaked`).toBe(false);
	}
	// Voices: exactly the identity's list, never the host's.
	expect(probe.voices.map((v: string) => v.split("|")[0]).sort()).toEqual(
		config.voices.map((v: any) => v.name).sort(),
	);
	if (probe.webgl) {
		expect(probe.webgl.vendor).toBe(config["webGl:vendor"]);
		expect(probe.webgl.renderer).toBe(config["webGl:renderer"]);
	}
	// Playwright's media emulation is off, so the host answers: headless is
	// light; headful follows the desktop theme.
	if (!headful) expect(probe.media.colorScheme).toBe("light");
	// Stock Firefox's max_entries: the history starts at 1.
	expect(probe.historyLength).toBe(1);
	// The storage quota is the stock-profile disk's, not the temp dir's.
	expect(typeof probe.storageQuota).toBe("number");
	expect(probe.mediaDevices.length).toBeGreaterThan(0);
}

describe.runIf(ENABLED)("e2e: the TS launcher drives a real Camoufox", () => {
	let mods: {
		sync: typeof import("../src/sync_api.js");
		server: typeof import("../src/server.js");
		utils: typeof import("../src/utils.js");
		warnings: typeof import("../src/warnings.js");
	};
	const results: Record<string, any> = {};

	beforeAll(async () => {
		mods = {
			sync: await import("../src/sync_api.js"),
			server: await import("../src/server.js"),
			utils: await import("../src/utils.js"),
			warnings: await import("../src/warnings.js"),
		};
	});

	for (const identity of Object.keys(IDENTITIES)) {
		describe(identity, () => {
			it("builds the same CAMOU_CONFIG as Python", async () => {
				const { result } = await mods.warnings.recordWarnings(() =>
					mods.utils.launchOptions(kwargsFor(identity)),
				);
				const config = configOf(result as Record<string, any>);
				results[`${identity}:config`] = config;
				const py = await pythonProbe("config-only", kwargsFor(identity));
				expect(config).toEqual(py.config);
			}, 240_000);

			it("headless: the page sees the configured identity, same as Python", async () => {
				const { result: browser } = await mods.warnings.recordWarnings(() =>
					mods.sync.Camoufox(kwargsFor(identity)),
				);
				let probe: any;
				try {
					const page = await (browser as any).newPage();
					probe = await probePage(page);
				} finally {
					await (browser as any).close();
				}
				results[`${identity}:headless`] = probe;

				// A second launch of the same identity presents the same device.
				const { result: again } = await mods.warnings.recordWarnings(() =>
					mods.sync.Camoufox(kwargsFor(identity)),
				);
				try {
					expect(
						stable(await probePage(await (again as any).newPage())),
					).toEqual(stable(probe));
				} finally {
					await (again as any).close();
				}

				const py = await pythonProbe("headless", kwargsFor(identity));
				expect(stable(probe)).toEqual(stable(py.probe));
			}, 240_000);

			it("persistent context: same identity, same as Python", async () => {
				const profile = fs.mkdtempSync(
					path.join(os.tmpdir(), "camoufox-e2e-profile-"),
				);
				let probe: any;
				try {
					const { result: context } = await mods.warnings.recordWarnings(() =>
						mods.sync.Camoufox({
							...kwargsFor(identity),
							persistent_context: true,
							user_data_dir: profile,
						}),
					);
					try {
						const page = await (context as any).newPage();
						probe = await probePage(page);
					} finally {
						await (context as any).close();
					}
				} finally {
					fs.rmSync(profile, { recursive: true, force: true });
				}
				results[`${identity}:persistent`] = probe;

				const py = await pythonProbe("persistent", kwargsFor(identity));
				expect(stable(probe)).toEqual(stable(py.probe));
			}, 240_000);

			it("launchServer: a connected client sees the same identity", async () => {
				const { firefox } = await import("playwright-core");
				const { result: bs } = await mods.warnings.recordWarnings(() =>
					mods.server.launchServer(kwargsFor(identity)),
				);
				const browserServer = bs as import("playwright-core").BrowserServer;
				let probe: any;
				try {
					const browser = await firefox.connect(browserServer.wsEndpoint());
					try {
						// A remote client gets plain Playwright: no Camoufox defaults,
						// so ask for them explicitly (as a Python client would).
						const config = results[`${identity}:config`];
						const spoofsWindow = Object.keys(config).some((k) =>
							/^(window\.(outer|inner)|document\.body\.client)/.test(k),
						);
						const page = await browser.newPage({
							...(spoofsWindow ? { viewport: null } : {}),
							...mods.utils.STOCK_MEDIA_DEFAULTS,
						});
						probe = await probePage(page);
					} finally {
						await browser.close();
					}
				} finally {
					await browserServer.close();
				}
				results[`${identity}:server`] = probe;
				expect(stable(probe)).toEqual(stable(results[`${identity}:headless`]));
			}, 240_000);

			it("NewContext: a per-context identity, same as Python", async () => {
				// A different identity from the launch one, so a context that
				// inherited the browser's identity would be caught.
				const preset =
					identity === "fpgen_linux_de"
						? INPUTS.presets.windows
						: INPUTS.presets.macos;
				const { result: browser } = await mods.warnings.recordWarnings(() =>
					mods.sync.Camoufox(kwargsFor(identity)),
				);
				let probe: any;
				let second: any;
				try {
					const context = await mods.sync.NewContext(browser as any, {
						preset,
					});
					probe = await probePage(await context.newPage());
					// The HTTP header must tell the same story as navigator: a
					// context that dropped its userAgent option sent the
					// browser's own UA here while navigator was spoofed.
					expect(lastRequestUserAgent).toBe(probe.navigator.userAgent);
					// Contexts are isolated: another preset, another device.
					const other = await mods.sync.NewContext(browser as any, {
						preset: INPUTS.presets.linux,
					});
					second = await probePage(await other.newPage());
				} finally {
					await (browser as any).close();
				}
				const launch = results[`${identity}:headless`];
				expect(probe.navigator.userAgent).not.toBe(launch.navigator.userAgent);
				expect(second.navigator.userAgent).not.toBe(probe.navigator.userAgent);

				// Per-context noise seeds are drawn fresh in both launchers, so
				// compare the identity itself, not the noise.
				const identityOf = (p: any) => ({
					navigator: p.navigator,
					screen: p.screen,
					timeZone: p.intl.timeZone,
					webgl: p.webgl,
				});
				const py = await pythonProbe("context", kwargsFor(identity), {
					preset,
				});
				expect(identityOf(probe)).toEqual(identityOf(py.probe));
			}, 240_000);

			it("the browser honours the config (headless, persistent, launchServer)", async (ctx) => {
				const config = results[`${identity}:config`];
				const missing = unknownToBinary(config);
				if (missing.length)
					ctx.skip(
						`binary predates the launcher; it does not know: ${missing.join(", ")}`,
					);
				for (const mode of ["headless", "persistent", "server"]) {
					expect(results[`${identity}:${mode}`], mode).toBeTruthy();
					expectMatchesConfig(results[`${identity}:${mode}`], config);
				}
				// A persistent profile presents the same device as a throwaway one.
				// (beta.30 did not: its storage quota was Firefox's pinned 10 GiB
				// headless and the disk's in a profile -- LEAKS row 107.)
				expect(stable(results[`${identity}:persistent`])).toEqual(
					stable(results[`${identity}:headless`]),
				);
			});

			it.runIf(identity === "fpgen_linux_de" && process.platform === "linux")(
				"pin_cpu_cores: the browser runs on as many cores as it reports",
				async () => {
					const selfCores = () =>
						fs
							.readFileSync("/proc/self/status", "utf-8")
							.match(/Cpus_allowed_list:\s*(.+)/)?.[1];
					const before = selfCores();
					const { result: browser } = await mods.warnings.recordWarnings(() =>
						mods.sync.Camoufox({ ...kwargsFor(identity), pin_cpu_cores: true }),
					);
					try {
						const page = await (browser as any).newPage();
						await page.goto(url);
						const reported = await page.evaluate(
							"navigator.hardwareConcurrency",
						);
						// The launching process got its cores back...
						expect(selfCores()).toBe(before);
						// ...and the browser it spawned runs on exactly `reported` cores.
						const { parseCpuList } = await import("../src/cpu_affinity.js");
						const children = fs
							.readFileSync(
								`/proc/${process.pid}/task/${process.pid}/children`,
								"utf-8",
							)
							.trim()
							.split(/\s+/)
							.filter((pid) => {
								try {
									return (
										fs.readFileSync(`/proc/${pid}/comm`, "utf-8").trim() ===
										"camoufox-bin"
									);
								} catch {
									return false;
								}
							});
						expect(children.length).toBeGreaterThan(0);
						for (const pid of children) {
							const list =
								fs
									.readFileSync(`/proc/${pid}/status`, "utf-8")
									.match(/Cpus_allowed_list:\s*(.+)/)?.[1] ?? "";
							expect(parseCpuList(list)).toHaveLength(reported);
						}
					} finally {
						await (browser as any).close();
					}
				},
				240_000,
			);

			it.runIf(identity === "fpgen_linux_de" && process.platform === "linux")(
				"headless: 'virtual' runs headful on a private Xvfb and tears it down",
				async () => {
					const { result: browser } = await step(
						"virtual: launch (Xvfb + headful browser)",
						mods.warnings.recordWarnings(() =>
							mods.sync.Camoufox({
								...kwargsFor(identity),
								headless: "virtual",
							}),
						),
					);
					const display = (browser as any)._virtualDisplay;
					expect(display).toBeTruthy();
					let probe: any;
					try {
						const page = await step(
							"virtual: newPage",
							(browser as any).newPage(),
						);
						// Firefox defers enumerateDevices() until the document has
						// focus (LEAKS row 57). Headless fakes focus; a headful window
						// on a bare Xvfb only sometimes gets it, so the probe hung on
						// some runs. A user's window has focus: give it one.
						await step("virtual: goto", page.goto(url));
						await step("virtual: focus", focusPage(page));
						probe = await step(
							"virtual: probe the page",
							page.evaluate(`(${PROBE})()`),
						);
					} finally {
						await step("virtual: close", (browser as any).close());
					}
					// close() killed the Xvfb it spawned.
					expect(display.proc ?? null).toBeNull();
					results[`${identity}:virtual`] = probe;

					// Parity: Python's headless="virtual" on the same binary.
					const py = await pythonProbe("virtual", kwargsFor(identity));
					expect(stable(probe)).toEqual(stable(py.probe));
				},
				240_000,
			);

			it.runIf(identity === "fpgen_linux_de" && process.platform === "linux")(
				"the browser honours the config headful, as it does headless",
				async (ctx) => {
					const config = results[`${identity}:config`];
					const missing = unknownToBinary(config);
					if (missing.length)
						ctx.skip(
							`binary predates the launcher; it does not know: ${missing.join(", ")}`,
						);
					const probe = results[`${identity}:virtual`];
					expect(probe, "the virtual-display test ran").toBeTruthy();
					expectMatchesConfig(probe, config, true);
					// A headful window presents the same device as headless. On a
					// runner with no media hardware, published beta.31 never settled
					// enumerateDevices() headful while headless answered.
					const { media: _m, ...headful } = stable(probe);
					const { media: _h, ...headless } = stable(
						results[`${identity}:headless`],
					);
					expect(headful).toEqual(headless);
				},
				240_000,
			);
		});
	}
});
