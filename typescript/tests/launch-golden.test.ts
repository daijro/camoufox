/**
 * launchOptions() must reproduce Python's launch_options() exactly.
 *
 * The goldens in tests/fixtures/launch are recorded by
 * scripts/golden/launch_golden.py (run it with the repo's .venv python). Each
 * scenario is replayed here with the same pinned host probes, and everything
 * launch_options() returns is compared: the CAMOU_CONFIG blob byte for byte
 * (and its chunking), CAMOU_PREFS, firefoxUserPrefs, args, env, the generated
 * fontconfig, the warnings in order, stdout, and any error.
 *
 * Linux only: the goldens are recorded there (chunk size and fontconfig depend
 * on the host OS).
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PyFloat, parsePyJson } from "../src/pycompat.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.join(HERE, "fixtures", "launch");
const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-golden-ts-"));
const XDG = path.join(SCRATCH, "xdg-cache");
const CACHE = path.join(XDG, "camoufox");
const HOME = path.join(SCRATCH, "home");

// parsePyJson: the fresh salt is a 64-bit int, beyond a JS number.
const hostInfo = parsePyJson(
	fs.readFileSync(path.join(FIXTURES, "host.json"), "utf-8"),
);
const HOST = hostInfo.host;
const GEO_TABLE: Record<string, any> = hostInfo.geo_table;
const INPUTS = JSON.parse(
	fs.readFileSync(path.join(FIXTURES, "inputs.json"), "utf-8"),
);
const SCENARIOS: any[] = (hostInfo.scenarios as string[]).map((name) =>
	JSON.parse(
		fs.readFileSync(path.join(FIXTURES, `scenario-${name}.json`), "utf-8"),
	),
);

// Scenarios whose INPUT carries a Python float that is integral (1920.0). A
// JS caller has to spell that as a PyFloat to get Python's bytes; these do.
const FLOAT_INPUTS: Record<string, (kwargs: any) => void> = {
	config_float_int: (kwargs) => {
		kwargs.config["screen.width"] = new PyFloat(kwargs.config["screen.width"]);
	},
};
const JS_EQUIVALENT_BLOB = new Set<string>();

const PLACEHOLDERS: Array<[string, string]> = [
	[path.join(FIXTURES, "bundle-old"), "<BUNDLE_OLD>"],
	[path.join(FIXTURES, "bundle"), "<BUNDLE>"],
	[path.join(FIXTURES, "addons", "example-addon"), "<ADDON>"],
	[CACHE, "<CACHE>"],
	[HOME, "<HOME>"],
];

function fill(value: any): any {
	if (typeof value === "string") {
		let out = value;
		for (const [real, ph] of PLACEHOLDERS) out = out.split(ph).join(real);
		return out;
	}
	if (Array.isArray(value)) return value.map(fill);
	if (value && typeof value === "object") {
		return Object.fromEntries(
			Object.entries(value).map(([k, v]) => [k, fill(v)]),
		);
	}
	return value;
}

function mask(value: any): any {
	if (typeof value === "string") {
		let out = value;
		for (const [real, ph] of PLACEHOLDERS) out = out.split(real).join(ph);
		// A FallbackWarning's report block names the host and the runtime
		// (python/node), so neither launcher can reproduce the other's.
		out = out.replace(/(and include:\n\n)( {4}.*(\n|$))+/g, "$1<REPORT>");
		return out.replace(/fonts-[0-9a-f]{12}\.conf/g, "fonts-<HASH>.conf");
	}
	if (Array.isArray(value)) return value.map(mask);
	if (value && typeof value === "object") {
		return Object.fromEntries(
			Object.entries(value).map(([k, v]) => [mask(k), mask(v)]),
		);
	}
	return value;
}

/** camoufox.server.camel_case, for keys that are snake_case. */
function camel(key: string): string {
	if (!key.includes("_")) return key;
	const parts = key.toLowerCase().split("_");
	const joined = parts
		.map((x) => (x ? x[0].toUpperCase() + x.slice(1) : ""))
		.join("");
	return joined[0].toLowerCase() + joined.slice(1);
}

/** Where two strings first differ, with some context either side. */
function firstDiff(have: string, want: string): string {
	if (have === want) return "";
	let i = 0;
	while (i < have.length && have[i] === want[i]) i++;
	const from = Math.max(0, i - 120);
	return `first difference at ${i}:\n  ts: ${have.slice(from, i + 120)}\n  py: ${want.slice(from, i + 120)}`;
}

/** Python exception type -> the TS error name it corresponds to. */
let mods: {
	utils: typeof import("../src/utils.js");
	fingerprints: typeof import("../src/fingerprints.js");
	locales: typeof import("../src/locales.js");
	geolocation: typeof import("../src/geolocation.js");
	warnings: typeof import("../src/warnings.js");
};

const ORIGINAL_ENV = { ...process.env };

beforeAll(async () => {
	// INSTALL_DIR is computed at import time, so point the cache first.
	process.env.XDG_CACHE_HOME = XDG;
	fs.mkdirSync(HOME, { recursive: true });
	mods = {
		utils: await import("../src/utils.js"),
		fingerprints: await import("../src/fingerprints.js"),
		locales: await import("../src/locales.js"),
		geolocation: await import("../src/geolocation.js"),
		warnings: await import("../src/warnings.js"),
	};
	expect(mods.utils.utilsDeps.installDir()).toBe(CACHE);

	// The mmdb files only have to exist and be fresh; the fake reader answers.
	fs.mkdirSync(mods.geolocation.MMDB_DIR, { recursive: true });
	for (const name of [
		"maxmind geolite2-ipv4.mmdb",
		"maxmind geolite2-ipv6.mmdb",
	]) {
		fs.writeFileSync(path.join(mods.geolocation.MMDB_DIR, name), "");
	}
	// The default addon, already "downloaded", so nothing is fetched.
	fs.mkdirSync(path.join(CACHE, "addons", "UBO"), { recursive: true });
	fs.writeFileSync(path.join(CACHE, "addons", "UBO", "manifest.json"), "{}");

	const deps = mods.utils.utilsDeps;
	const realFix = mods.fingerprints.fixHardwareConcurrency;
	deps.fixHardwareConcurrency = (config, canPin) =>
		realFix(config, canPin, { cpuCount: HOST.cpu_count, canPinHost: true });
	deps.stockProfileDiskCapacityKb = () => HOST.disk_capacity_kb;
	deps.hostOsKey = () => HOST.host_os_key;
	deps.largestDisplay = () => ({
		width: HOST.display[0],
		height: HOST.display[1],
	});
	deps.publicIp = async () => HOST.public_ip;
	const realSalt = mods.fingerprints.identitySalt;
	deps.identitySalt = (pinned?: unknown) =>
		pinned === undefined || pinned === null
			? BigInt(HOST.fresh_salt as bigint)
			: realSalt(pinned);
	mods.locales.localeDeps.random = () => HOST.locale_uniform;
	mods.geolocation.geoipDeps.openDatabase = async () => ({
		get: (ip: string) => structuredClone(GEO_TABLE[ip] ?? null),
	});
}, 120_000);

afterAll(() => {
	process.env = ORIGINAL_ENV;
	fs.rmSync(SCRATCH, { recursive: true, force: true });
});

async function replay(scenario: any) {
	const deps = mods.utils.utilsDeps;
	const kwargs = fill(structuredClone(scenario.kwargs));
	const special = scenario.special ?? {};
	const calls: any[] = [];
	const stdout: string[] = [];
	const restore: Array<() => void> = [];

	if (kwargs.executable_path === null) delete kwargs.executable_path;
	FLOAT_INPUTS[scenario.name]?.(kwargs);

	const printBefore = deps.print;
	deps.print = (line: string) => {
		stdout.push(`${line}\n`);
	};
	restore.push(() => {
		deps.print = printBefore;
	});

	if (special.generate) {
		const base = INPUTS.fingerprints[special.generate];
		const before = deps.generateFingerprint;
		deps.generateFingerprint = async ({ window, screen, os: osOpt }: any) => {
			calls.push({
				fn: "generate_fingerprint",
				window: window ? [...window] : null,
				screen: screen
					? {
							min_width: screen.minWidth,
							max_width: screen.maxWidth,
							min_height: screen.minHeight,
							max_height: screen.maxHeight,
						}
					: null,
				os: osOpt ?? null,
			});
			const fp = structuredClone(base);
			if (window) mods.fingerprints.handleWindowSize(fp, window[0], window[1]);
			return fp;
		};
		restore.push(() => {
			deps.generateFingerprint = before;
		});
	}
	if (special.random_preset) {
		const preset = INPUTS.presets[special.random_preset];
		const before = deps.getRandomPreset;
		deps.getRandomPreset = ((osOpt: any, ffVersion: any) => {
			calls.push({
				fn: "get_random_preset",
				os: osOpt ?? null,
				ff_version: ffVersion ?? null,
			});
			return structuredClone(preset);
		}) as any;
		restore.push(() => {
			deps.getRandomPreset = before;
		});
	}
	for (const [k, v] of Object.entries(special.process_env ?? {})) {
		const prev = process.env[k];
		process.env[k] = fill(v);
		restore.push(() => {
			if (prev === undefined) delete process.env[k];
			else process.env[k] = prev;
		});
	}

	try {
		const { result, error, warnings } = await mods.warnings.recordWarnings(() =>
			mods.utils.launchOptions(kwargs),
		);
		return { result, error, warnings, stdout: stdout.join(""), calls };
	} finally {
		for (const undo of restore.reverse()) undo();
	}
}

function describeResult(result: Record<string, any>) {
	const env: Record<string, any> = { ...result.env };
	const chunks = (prefix: string) =>
		Object.keys(env)
			.filter((k) => k.startsWith(prefix))
			.map((k) => [Number.parseInt(k.slice(prefix.length), 10), k] as const)
			.sort((a, b) => a[0] - b[0])
			.map(([, k]) => k);
	const configKeys = chunks("CAMOU_CONFIG_");
	const prefKeys = chunks("CAMOU_PREFS_");
	let fontconfig: any = null;
	if (env.FONTCONFIG_FILE) {
		const file = String(env.FONTCONFIG_FILE);
		const content = fs.readFileSync(file, "utf-8");
		// The file is named for the hash of its (unmasked) content.
		const hash = createHash("sha256")
			.update(content)
			.digest("hex")
			.slice(0, 12);
		expect(path.basename(file)).toBe(`fonts-${hash}.conf`);
		fontconfig = { path: mask(file), content: mask(content) };
	}
	const otherEnv = Object.fromEntries(
		Object.entries(env).filter(
			([k]) => !k.startsWith("CAMOU_CONFIG_") && !k.startsWith("CAMOU_PREFS_"),
		),
	);
	const { env: _env, ...rest } = result;
	return {
		options: mask(rest),
		env: mask(otherEnv),
		config_chunks: configKeys.map((k) => Array.from(String(env[k])).length),
		prefs_chunks: prefKeys.map((k) => String(env[k]).length),
		config_blob: mask(configKeys.map((k) => env[k]).join("")),
		prefs_blob: prefKeys.map((k) => env[k]).join(""),
		fontconfig,
	};
}

describe.skipIf(process.platform !== "linux")(
	"launchOptions() matches Python launch_options()",
	() => {
		it("replays every recorded scenario", () => {
			expect(SCENARIOS.length).toBeGreaterThan(80);
		});

		for (const scenario of SCENARIOS) {
			it(scenario.name, async () => {
				const got = await replay(scenario);

				// Errors
				if (scenario.error) {
					expect(got.error, "expected an error").toBeDefined();
					const err = got.error as Error;
					expect(err.name).toBe(scenario.error.type);
					expect(mask(err.message)).toBe(scenario.error.message);
				} else if (got.error) {
					throw got.error;
				}

				expect(mask(got.warnings)).toEqual(scenario.warnings);
				expect(mask(got.stdout)).toBe(scenario.stdout);
				expect(mask(got.calls)).toEqual(scenario.calls);
				if (scenario.error) return;

				const want = scenario.result;
				const have = describeResult(got.result as Record<string, any>);

				// The config blob, byte for byte.
				const wantBlob = JS_EQUIVALENT_BLOB.has(scenario.name)
					? want.config_blob_js
					: (want.config_blob_raw ?? want.config_blob_js);
				expect(have.config_blob, firstDiff(have.config_blob, wantBlob)).toBe(
					wantBlob,
				);
				// Chunking: same number of CAMOU_CONFIG_<n>, every one but the last
				// full. (Exact lengths differ by the scratch-path length.)
				const full = (c: number[]) => c.slice(0, -1).every((n) => n === 32767);
				expect(have.config_chunks.length).toBe(want.config_chunks.length);
				expect(full(have.config_chunks)).toBe(true);
				expect(full(want.config_chunks)).toBe(true);

				expect(have.prefs_blob).toBe(want.prefs_blob);
				expect(have.prefs_chunks).toEqual(want.prefs_chunks);

				const wantOptions = Object.fromEntries(
					Object.entries(want.options).map(([k, v]) => [camel(k), v]),
				);
				const haveOptions = Object.fromEntries(
					Object.entries(have.options).map(([k, v]) => [camel(k), v]),
				);
				expect(haveOptions).toEqual(mask(wantOptions));

				expect(have.env).toEqual(mask(want.env));
				expect(have.fontconfig).toEqual(mask(want.fontconfig));
			});
		}
	},
);
