/**
 * Launch-option assembly: turns Camoufox's high-level options into the
 * Playwright Firefox launch options plus the CAMOU_CONFIG environment.
 *
 * TypeScript twin of pythonlib/camoufox/utils.py. `launchOptions()` must
 * produce what Python's `launch_options()` produces for the same inputs; the
 * goldens in tests/fixtures/launch (scripts/golden/launch_golden.py) hold it
 * to that.
 *
 * Every collaborator is reached through `utilsDeps`, the counterpart of the
 * module globals the Python tests monkeypatch (`utils.generate_fingerprint`,
 * `utils._stock_profile_disk_capacity_kb`, ...). Production code never
 * touches it.
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { inspect } from "node:util";
import { UAParser } from "ua-parser-js";
import { addDefaultAddons, confirmPaths, type DefaultAddon } from "./addons.js";
import * as coherence from "./coherence.js";
import * as cpuAffinity from "./cpu_affinity.js";
import { hasDisplay, largestDisplay } from "./display.js";
import {
	InvalidOS,
	InvalidPropertyType,
	NonFirefoxFingerprint,
} from "./exceptions.js";
import {
	audioSeedFromIdentity,
	clampScreenToDisplay,
	clampWindowDimensions,
	clampWindowPosition,
	fixHardwareConcurrency,
	fixNavigatorArch,
	fixScreenNoTaskbar,
	fromFpgen,
	fromPreset,
	generateFingerprint,
	generateRandomFontSubset,
	generateRandomVoiceSubset,
	getRandomPreset,
	identitySalt,
	identitySeed,
	raiseScreenToModernFloor,
	Screen,
	setMediaDevicesDefaults,
	WINDOWS_11_MARKER_FONTS,
} from "./fingerprints.js";
import { ensureModel } from "./fpgen/index.js";
import { geoipAllowed, getGeolocation } from "./geolocation.js";
import {
	type ProxyConfig,
	ProxyHelper,
	publicIP,
	validIPv4,
	validIPv6,
} from "./ip.js";
import { handleLocales } from "./locales.js";
import {
	effectiveVersionMin,
	ensureBrowserProfileDir,
	ensureCamoufoxInstalled,
	getPath,
	INSTALL_DIR,
	installedVerStr,
	LOCAL_DATA,
	launchPath,
	OS_NAME,
	resolvedPlaywrightVersionStr,
	Version,
} from "./pkgman.js";
import {
	formatPyFloatRepr,
	isPyError,
	orjsonDumps,
	PyFloat,
	pyRepr,
	pyStr,
	ValueError,
} from "./pycompat.js";
import type { VirtualDisplay } from "./virtdisplay.js";
import { FallbackWarning, LeakWarning, warn } from "./warnings.js";
import { sampleWebglForScreen, webglForGpu } from "./webgl.js";

export type ListOrString = string | string[];
export type TargetOS = "mac" | "win" | "lin";
export type EnvVars = Record<string, string | number | boolean>;

// Camoufox preferences to cache previous pages and requests
export const CACHE_PREFS: Record<string, any> = {
	"browser.sessionhistory.max_entries": 10,
	"browser.sessionhistory.max_total_viewers": -1,
	"browser.cache.memory.enable": true,
	"browser.cache.disk_cache_ssl": true,
	"browser.cache.disk.smart_size.enabled": true,
};

/** The host OS in fonts.json / target_os terms ('mac', 'win', 'lin'). */
function hostOsKey(): TargetOS | null {
	return (
		({ darwin: "mac", win32: "win", linux: "lin" } as Record<string, TargetOS>)[
			process.platform
		] ?? null
	);
}

// navigator.storage.estimate().quota is not a constant: Gecko derives it from
// the disk. GetTemporaryStorageLimit() (dom/quota/ActorsParent.cpp) takes
// nsIFile::GetDiskCapacity() of the storage directory and halves it, then
// QuotaManager::GetGroupLimitForLimit() reports min(that / 5, 10 GiB) to the
// page -- so any disk of 100 GB or more reads back as exactly 10 GiB, and a
// smaller one as its own capacity / 10.
export const QUOTA_FIXED_LIMIT_PREF =
	"dom.quotaManager.temporaryStorage.fixedLimit";
// The pref is a signed 32-bit int in KB. Any value above 50 GiB already reports
// the 10 GiB group cap, so clamping a multi-terabyte disk changes nothing a page
// can see.
const INT32_MAX = 2 ** 31 - 1;

/** shutil.disk_usage(path).total */
function diskTotal(p: string): number {
	const st = fs.statfsSync(p);
	return st.blocks * st.bsize;
}

/**
 * Half the capacity of the disk a stock Firefox profile would live on, in KB.
 *
 * That is the number Gecko's own GetTemporaryStorageLimit() would compute on
 * this machine, and it is what `dom.quotaManager.temporaryStorage.fixedLimit`
 * takes. The disk a stock profile lives on, not the one Playwright's throwaway
 * profile lands on: on a host whose temp directory is a tmpfs, that profile
 * sits on a RAM-sized volume no real Firefox profile would.
 */
function stockProfileDiskCapacityKb(): number | null {
	const home = os.homedir();
	let candidates: string[];
	const osName = utilsDeps.osName();
	if (osName === "win") {
		const appdata = process.env.APPDATA;
		candidates = [appdata ? path.join(appdata, "Mozilla") : home, home];
	} else if (osName === "mac") {
		candidates = [
			path.join(home, "Library", "Application Support", "Firefox"),
			home,
		];
	} else {
		candidates = [path.join(home, ".mozilla"), home];
	}

	for (const candidate of candidates) {
		// The directory only exists if Firefox has ever run here; walk up to the
		// first path that does, which is on the same filesystem anyway.
		let probe = candidate;
		while (!fs.existsSync(probe) && probe !== path.dirname(probe)) {
			probe = path.dirname(probe);
		}
		let total: number;
		try {
			total = utilsDeps.diskTotal(probe);
		} catch {
			continue;
		}
		if (total > 0) {
			return Math.min(Math.floor(Math.floor(total / 2) / 1024), INT32_MAX);
		}
	}
	return null;
}

/**
 * Injection points: everything launchOptions() reaches outside this module.
 * Mirrors the names the Python tests monkeypatch on camoufox.utils.
 */
export const utilsDeps = {
	osName: (): TargetOS => OS_NAME,
	installDir: (): string => INSTALL_DIR,
	hostOsKey,
	diskTotal,
	stockProfileDiskCapacityKb,
	hasDisplay,
	largestDisplay,
	getScreenCons: (headless?: boolean) => getScreenCons(headless),
	print: (line: string): void => {
		process.stdout.write(`${line}\n`);
	},
	ensureBrowserProfileDir,
	ensureCamoufoxInstalled,
	addDefaultAddons,
	confirmPaths,
	installedVerStr: () => installedVerStr(),
	effectiveVersionMin,
	resolvedPlaywrightVersionStr,
	getPath,
	launchPath,
	identitySalt,
	identitySeed,
	generateFingerprint: async (
		options: Parameters<typeof generateFingerprint>[0],
	): Promise<Record<string, any>> => {
		// fpgen's model is fetched on first use, like Python's.
		await ensureModel();
		return generateFingerprint(options);
	},
	fromFpgen,
	fromPreset,
	getRandomPreset,
	fixNavigatorArch,
	fixHardwareConcurrency,
	fixScreenNoTaskbar,
	clampScreenToDisplay,
	clampWindowDimensions,
	clampWindowPosition,
	raiseScreenToModernFloor,
	generateRandomFontSubset,
	generateRandomVoiceSubset,
	setMediaDevicesDefaults,
	// The WebGL draws read fpgen's model, fetched on first use like Python's.
	webglForGpu: async (...args: Parameters<typeof webglForGpu>) => {
		await ensureModel();
		return webglForGpu(...args);
	},
	sampleWebglForScreen: async (
		...args: Parameters<typeof sampleWebglForScreen>
	) => {
		await ensureModel();
		return sampleWebglForScreen(...args);
	},
	publicIp: publicIP,
	getGeolocation,
	validateConfig: (config: Record<string, any>, p?: string | null) =>
		validateConfig(config, p),
	getEnvVars: (config: Record<string, any>, uaOs: string, p?: string | null) =>
		getEnvVars(config, uaOs, p),
	findInstalledVersion: async (spec: string): Promise<string | null> =>
		(await import("./multiversion.js")).findInstalledVersion(spec) ?? null,
};

/*
 * Python-compatible serialisation helpers
 */

/** type(value).__name__ for a JSON-ish value. */
export function pyTypeName(value: unknown): string {
	if (value === null || value === undefined) return "NoneType";
	if (typeof value === "boolean") return "bool";
	if (value instanceof PyFloat) return "float";
	if (typeof value === "number")
		return Number.isInteger(value) ? "int" : "float";
	if (typeof value === "bigint") return "int";
	if (typeof value === "string") return "str";
	if (Array.isArray(value)) return "list";
	return "dict";
}

/**
 * json.dumps(value, ensure_ascii=True, separators=(',', ':')): compact, every
 * non-ASCII (and DEL) character \u-escaped, floats in Python's repr.
 */
export function pyJsonDumpsAscii(value: unknown): string {
	const encode = (v: unknown): string => {
		if (v === null || v === undefined) return "null";
		if (v === true) return "true";
		if (v === false) return "false";
		if (typeof v === "number") {
			if (Number.isInteger(v)) return String(v);
			if (Number.isNaN(v)) return "NaN";
			if (!Number.isFinite(v)) return v > 0 ? "Infinity" : "-Infinity";
			return formatPyFloatRepr(v);
		}
		if (typeof v === "bigint") return v.toString();
		if (v instanceof PyFloat) return formatPyFloatRepr(v.value);
		if (typeof v === "string") {
			return JSON.stringify(v).replace(
				/[\u007f-￿]/g,
				(c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`,
			);
		}
		if (Array.isArray(v)) return `[${v.map(encode).join(",")}]`;
		return `{${Object.entries(v as Record<string, unknown>)
			.map(([k, x]) => `${encode(k)}:${encode(x)}`)
			.join(",")}}`;
	};
	return encode(value);
}

/**
 * orjson.dumps(config): compact, UTF-8, insertion order. JavaScript has one
 * number type, so the Python int/float split is carried the way pycompat
 * carries it: a safe-integer number is an int, a bigint is an int beyond
 * 2**53, a PyFloat is an integral float, and any other number is a float.
 */
export function configJson(value: unknown): string {
	return orjsonDumps(value, false);
}

/** Slice `s` into chunks of `size` code points (Python str slicing). */
function chunkCodePoints(s: string, size: number): string[] {
	// Fast path: no astral characters, so UTF-16 units == code points.
	if (!/[\ud800-\udfff]/.test(s)) {
		const out: string[] = [];
		for (let i = 0; i < s.length; i += size) out.push(s.slice(i, i + size));
		return out;
	}
	const cps = Array.from(s);
	const out: string[] = [];
	for (let i = 0; i < cps.length; i += size) {
		out.push(cps.slice(i, i + size).join(""));
	}
	return out;
}

/*
 * Environment
 */

/**
 * Generates a runtime fontconfig that resolves bundled font paths absolutely.
 * The bundled fonts.conf uses prefix="cwd" relative paths which break when
 * Playwright's working directory differs from the browser install directory.
 * Writes a patched copy to the platform cache dir (deterministic, only
 * regenerated when content changes). This must not live inside the versioned
 * browser bundle: the bundle is commonly baked into an image as root and run
 * as a non-root user, so it is read-only at launch time.
 */
export function generateFontconfig(
	fontconfigPath: string,
	executablePath?: string | null,
	osDir?: string | null,
): string {
	// Beside the caller's own binary when they supplied one; see getEnvVars.
	const fontsDir = executablePath
		? path.join(path.dirname(executablePath), "fonts")
		: utilsDeps.getPath("fonts");

	// Which directories this identity's OS may see.
	//
	// fontconfig scans <dir> RECURSIVELY, so the parent must never be named: it
	// would make every other OS's files reachable by the renderer -- hidden by
	// the allowlist for direct lookups, but still candidates for glyph fallback.
	//
	// The bundle stores each face ONCE, in a directory named for the set of
	// OSes that use it (L, M, W, LM, LW, MW, LMW) -- see bundle/fonts/groups.json
	// and scripts/gen-font-groups.py. An OS reads the groups its letter appears
	// in, so nothing has to be hidden after the fact.
	let scanDirs: string[] = [];
	const groupsPath = path.join(fontsDir, "groups.json");
	const osKey = (
		{ linux: "lin", macos: "mac", windows: "win" } as Record<string, string>
	)[osDir ?? ""];
	if (osKey && fs.existsSync(groupsPath)) {
		try {
			const parsed = JSON.parse(fs.readFileSync(groupsPath, "utf-8"));
			const readBy: string[] = parsed?.readBy?.[osKey] ?? [];
			scanDirs = readBy
				.map((g) => path.join(fontsDir, g))
				.filter((d) => isDir(d));
		} catch {
			scanDirs = [];
		}
	}
	if (!scanDirs.length) {
		// Older bundles ship fonts/<os>/ with each OS's set duplicated in full.
		if (osDir && isDir(path.join(fontsDir, osDir))) {
			scanDirs = [path.join(fontsDir, osDir)];
		} else {
			scanDirs = [fontsDir];
		}
	}

	const fontsConfSrc = path.join(fontconfigPath, "fonts.conf");
	let confContent = fs.readFileSync(fontsConfSrc, "utf-8");
	confContent = confContent.replace(
		'<dir prefix="cwd">fonts</dir>',
		scanDirs.map((d) => `<dir>${d}</dir>`).join("\n\t"),
	);

	// INSTALL_DIR is platformdirs' user_cache_dir("camoufox"); see paths.ts.
	const cacheDir = path.join(utilsDeps.installDir(), "fontconfig");
	fs.mkdirSync(cacheDir, { recursive: true });

	const contentHash = createHash("sha256")
		.update(confContent)
		.digest("hex")
		.slice(0, 12);
	const runtimeConf = path.join(cacheDir, `fonts-${contentHash}.conf`);
	if (!fs.existsSync(runtimeConf)) {
		fs.writeFileSync(runtimeConf, confContent);
	}
	return runtimeConf;
}

function isDir(p: string): boolean {
	try {
		return fs.statSync(p).isDirectory();
	} catch {
		return false;
	}
}

/**
 * Warn when a caller's own binary is older than their Playwright needs.
 *
 * A managed install below the floor is simply upgraded (pkgman resolves it),
 * but `executable_path` deliberately bypasses that. That leaves the one
 * pairing nothing checks: an old build driven by Playwright >= 1.61, which
 * sends viewport fields the older Juggler schema rejects. Warns rather than
 * raises: the default no-viewport path still works on an old build. A build
 * with no version.json beside it tells us nothing, so it is left alone.
 */
export function warnIfExecutablePredatesPlaywright(
	executablePath?: string | null,
): void {
	if (!executablePath) return;
	let installed: Version;
	try {
		installed = Version.fromPath(path.dirname(executablePath));
	} catch {
		return;
	}

	const required = utilsDeps.effectiveVersionMin();
	if (!installed.lessThan(required)) return;

	warn(
		`The Camoufox build at ${executablePath} is ${installed.build}, but Playwright ` +
			`${utilsDeps.resolvedPlaywrightVersionStr()} needs at least ${required.build}. ` +
			"Contexts created with an explicit viewport will fail with " +
			'"Protocol error (Browser.setDefaultViewport)". Update the build, or pin ' +
			"playwright<1.61.",
		"RuntimeWarning",
	);
}

/**
 * Pass the launcher's Firefox prefs to settings/camoufox.cfg, which applies them
 * at STARTUP (CAMOU_PREFS_1..N, chunked like CAMOU_CONFIG).
 *
 * Playwright's non-persistent launch writes no user.js: firefoxUserPrefs only
 * reach the browser at runtime, through juggler's Browser.enable, after
 * startup. Anything Gecko reads during startup therefore raced or never
 * applied.
 */
export function getPrefEnvVars(
	prefs: Record<string, any>,
): Record<string, string> {
	if (!prefs || !Object.keys(prefs).length) return {};
	// ASCII only: on Windows autoconfig's getenv() reads the environment through
	// the ANSI code page, which would mangle a raw UTF-8 pref value (\u escapes
	// survive it and JSON.parse restores them).
	const data = pyJsonDumpsAscii(prefs);
	const chunkSize = utilsDeps.osName() === "win" ? 2047 : 32767;
	const out: Record<string, string> = {};
	chunkCodePoints(data, chunkSize).forEach((chunk, i) => {
		out[`CAMOU_PREFS_${i + 1}`] = chunk;
	});
	return out;
}

/**
 * Gets the environment variables for Camoufox: the chunked CAMOU_CONFIG, plus
 * the Linux fontconfig pointer.
 *
 * `executablePath` is the caller's own executable, when they supplied one. The
 * bundled fontconfig is read from beside that binary rather than from the
 * managed install, the same way loadProperties() treats properties.json.
 */
export function getEnvVars(
	configMap: Record<string, any>,
	userAgentOs: string,
	executablePath?: string | null,
): EnvVars {
	const envVars: EnvVars = {};
	const configStr = configJson(configMap);

	// Split the config into chunks
	const osName = utilsDeps.osName();
	const chunkSize = osName === "win" ? 2047 : 32767;
	chunkCodePoints(configStr, chunkSize).forEach((chunk, i) => {
		envVars[`CAMOU_CONFIG_${i + 1}`] = chunk;
	});

	if (osName === "lin") {
		// https://github.com/coryking/camoufox/commit/f21eeb2850a74cc104fb57e17e0a2fa27b7a2a28
		// Thanks @coryking
		const directoryMap: Record<string, string> = {
			lin: "linux",
			mac: "macos",
			win: "windows",
		};
		const osDir = directoryMap[userAgentOs] ?? userAgentOs;

		// v150+ uses "fontconfig/" (matching the Go launcher); older bundles
		// shipped "fontconfigs/".
		const bundlePath = (...parts: string[]): string =>
			executablePath
				? path.join(path.dirname(executablePath), ...parts)
				: utilsDeps.getPath(path.join(...parts));

		let fontconfigPath = bundlePath("fontconfig", osDir);
		if (!fs.existsSync(path.join(fontconfigPath, "fonts.conf"))) {
			fontconfigPath = bundlePath("fontconfigs", osDir);
		}

		if (!fs.existsSync(path.join(fontconfigPath, "fonts.conf"))) {
			const err = new Error(
				`fonts.conf not found in ${fontconfigPath}!  Something ain't right with your camoufox bundle.`,
			);
			err.name = "FileNotFoundError";
			throw err;
		}

		envVars.FONTCONFIG_FILE = generateFontconfig(
			fontconfigPath,
			executablePath,
			osDir,
		);
	}

	return envVars;
}

/**
 * Loads the properties.json file.
 */
function loadProperties(
	executablePath?: string | null,
): Record<string, string> {
	let propFile: string;
	if (executablePath) {
		propFile = path.join(path.dirname(executablePath), "properties.json");
		if (!fs.existsSync(propFile)) {
			// macOS app bundle: the binary is Contents/MacOS/camoufox, the
			// packaged settings live in Contents/Resources/.
			const bundled = path.join(
				path.dirname(path.dirname(executablePath)),
				"Resources",
				"properties.json",
			);
			if (fs.existsSync(bundled)) propFile = bundled;
		}
	} else {
		propFile = utilsDeps.getPath("properties.json");
	}
	const propDict: Array<{ property: string; type: string }> = JSON.parse(
		fs.readFileSync(propFile, "utf-8"),
	);
	const out: Record<string, string> = {};
	for (const prop of propDict) out[prop.property] = prop.type;
	return out;
}

/**
 * Validates the config map.
 */
export function validateConfig(
	configMap: Record<string, any>,
	executablePath?: string | null,
): void {
	const propertyTypes = loadProperties(executablePath);

	for (const [key, value] of Object.entries(configMap)) {
		const expectedType = propertyTypes[key];
		if (!expectedType) {
			utilsDeps.print(`Skipping unknown patch ${key} : ${pyStr(value)}`);
			continue; // Property not supported by this browser version; skip silently
		}

		if (!validateType(value, expectedType)) {
			throw new InvalidPropertyType(
				`Invalid type for property ${key}. Expected ${expectedType}, got ${pyTypeName(value)}`,
			);
		}

		if (key === "voices") {
			validateVoices(value);
		}
	}
}

/**
 * Validates the type of the value. (Python's bool is an int, so a boolean
 * passes the numeric checks there, and here.)
 */
export function validateType(value: any, expectedType: string): boolean {
	if (value instanceof PyFloat) {
		// A Python float: int/uint only when it is integral (float.is_integer()).
		const v = value.value;
		if (expectedType === "double") return true;
		if (expectedType === "int") return Number.isInteger(v);
		if (expectedType === "uint") return Number.isInteger(v) && v >= 0;
		return false;
	}
	const isInt =
		typeof value === "boolean" ||
		typeof value === "bigint" ||
		(typeof value === "number" && Number.isInteger(value));
	switch (expectedType) {
		case "str":
			return typeof value === "string";
		case "int":
			return isInt;
		case "uint":
			return isInt && Number(value) >= 0;
		case "double":
			return typeof value === "number" || isInt;
		case "bool":
			return typeof value === "boolean";
		case "array":
			return Array.isArray(value);
		case "dict":
			return (
				typeof value === "object" && value !== null && !Array.isArray(value)
			);
		default:
			return false;
	}
}

// The five fields MaskConfig::MVoices() requires of every `voices` entry. It
// skips anything missing one of them, so a bare "Name:lang:type" string or a
// half-filled object registers nothing -- and a voice list that registers
// nothing leaves the host's native voices exposed (#731).
export const VOICE_FIELDS = [
	"lang",
	"name",
	"voiceUri",
	"isDefault",
	"isLocalService",
] as const;

/**
 * Validates that every `voices` entry is a complete voice object.
 */
export function validateVoices(voices: any): void {
	if (!Array.isArray(voices)) {
		throw new InvalidPropertyType(
			`Invalid type for property voices. Expected array, got ${pyTypeName(voices)}`,
		);
	}
	voices.forEach((voice, index) => {
		if (typeof voice !== "object" || voice === null || Array.isArray(voice)) {
			throw new InvalidPropertyType(
				`Invalid voices[${index}]: expected an object with ` +
					`{${VOICE_FIELDS.join(", ")}}, got ${pyTypeName(voice)} ` +
					`(${pyRepr(voice)}). Camoufox needs full voice objects, not names.`,
			);
		}
		const missing = VOICE_FIELDS.filter((field) => !(field in voice));
		if (missing.length) {
			throw new InvalidPropertyType(
				`Invalid voices[${index}]: missing ${missing.join(", ")}. ` +
					`Every voice needs {${VOICE_FIELDS.join(", ")}}.`,
			);
		}
	});
}

/**
 * Gets the OS from the config if the user agent is set, otherwise returns the
 * OS of the current system.
 */
export function getTargetOs(config: Record<string, any>): TargetOS {
	if (config["navigator.userAgent"]) {
		return determineUaOs(config["navigator.userAgent"]);
	}
	return utilsDeps.osName();
}

/**
 * Determines the OS from the user agent string.
 */
export function determineUaOs(userAgent: string): TargetOS {
	// Python's ua_parser answers "Other" rather than nothing for an
	// unrecognised UA, so its `raise` never fires and "lin" is what runs.
	const parsed = new UAParser(userAgent).getOS().name || "Other";
	// ua-parser-js reports "macOS"; the Python ua_parser reports "Mac OS X".
	if (parsed.startsWith("Mac") || parsed.startsWith("macOS")) return "mac";
	if (parsed.startsWith("Windows")) return "win";
	return "lin";
}

/**
 * Determines a sane viewport size for Camoufox if being ran in headful mode.
 *
 * Bounds are CSS pixels, the unit Firefox lays its windows out in -- see
 * display.ts for why that differs from the monitor's physical size.
 */
export function getScreenCons(headless?: boolean): Screen | null {
	if (headless === true) {
		return null; // Skip if headless
	}
	const display = utilsDeps.largestDisplay();
	if (display === null) {
		return null; // Skip if the display can't be probed
	}
	return new Screen({ maxWidth: display.width, maxHeight: display.height });
}

/**
 * Updates the fonts for the target OS.
 */
export function updateFonts(
	config: Record<string, any>,
	targetOs: string,
): void {
	const fonts: string[] = JSON.parse(
		fs.readFileSync(path.join(LOCAL_DATA, "fonts.json"), "utf-8"),
	)[targetOs];

	// Merge with existing fonts (np.unique sorts)
	if ("fonts" in config) {
		config.fonts = [...new Set([...fonts, ...config.fonts])].sort(pyCompare);
	} else {
		config.fonts = fonts;
	}
}

/** Python's str ordering: by code point, not UTF-16 unit. */
function pyCompare(a: string, b: string): number {
	const ca = Array.from(a);
	const cb = Array.from(b);
	for (let i = 0; i < Math.min(ca.length, cb.length); i++) {
		const d =
			(ca[i].codePointAt(0) as number) - (cb[i].codePointAt(0) as number);
		if (d) return d;
	}
	return ca.length - cb.length;
}

/**
 * Asserts that the passed fingerprint is a valid Firefox fingerprint, and
 * warns that passing one is not recommended.
 */
export function checkCustomFingerprint(fingerprint: Record<string, any>): void {
	const userAgent = fingerprint?.navigator?.userAgent || "";
	const browserName = parseUaFamily(userAgent);
	if (browserName !== "Firefox") {
		throw new NonFirefoxFingerprint(
			`"${browserName}" fingerprints are not supported in Camoufox. ` +
				"Using fingerprints from a browser other than Firefox WILL lead to detection. " +
				"If this is intentional, pass `i_know_what_im_doing=True`.",
		);
	}

	LeakWarning.warn("custom_fingerprint", false);
}

/** ua_parser.user_agent_parser.ParseUserAgent(ua)['family']. */
function parseUaFamily(userAgent: string): string {
	const name = new UAParser(userAgent).getBrowser().name;
	if (!name) return "Other";
	// ua-parser-js and uap-core name a few browsers differently.
	const map: Record<string, string> = {
		"Mobile Firefox": "Firefox Mobile",
		"Mobile Chrome": "Chrome Mobile",
		"Mobile Safari": "Mobile Safari",
	};
	return map[name] ?? name;
}

/**
 * Checks if the target OS is valid.
 */
export function checkValidOs(osValue: ListOrString): void {
	if (typeof osValue !== "string") {
		for (const osName of osValue) checkValidOs(osName);
		return;
	}
	// Assert that the OS is lowercase (str.islower(): has a cased char, none upper)
	if (
		!(osValue !== osValue.toUpperCase() && osValue === osValue.toLowerCase())
	) {
		throw new InvalidOS(`OS values must be lowercase: '${osValue}'`);
	}
	// Assert that the OS is supported by Camoufox
	if (!["windows", "macos", "linux"].includes(osValue)) {
		throw new InvalidOS(`Camoufox does not support the OS: '${osValue}'`);
	}
}

/**
 * Merges new keys/values from the source into the target, given that the key
 * does not exist in the target.
 */
export function mergeInto(
	target: Record<string, any>,
	source: Record<string, any>,
): void {
	for (const [key, value] of Object.entries(source)) {
		if (!(key in target)) target[key] = value;
	}
}

/**
 * Sets a new key/value into the target, given that the key does not exist.
 */
export function setInto(
	target: Record<string, any>,
	key: string,
	value: any,
): void {
	if (!(key in target)) target[key] = value;
}

/**
 * Checks if a domain is set in the config.
 */
export function isDomainSet(
	config: Record<string, any>,
	...properties: string[]
): boolean {
	for (const prop of properties) {
		// If the . prefix exists, check if the domain is a prefix of any key
		if (prop.endsWith(".") || prop.endsWith(":")) {
			if (Object.keys(config).some((key) => key.startsWith(prop))) return true;
		} else if (prop in config) {
			// Otherwise, check if the domain is a direct key in the config
			return true;
		}
	}
	return false;
}

/**
 * Warns the user if they are manually setting properties that Camoufox already
 * sets internally.
 */
export function warnManualConfig(config: Record<string, any>): void {
	// Manual locale setting
	if (
		isDomainSet(
			config,
			"navigator.language",
			"headers.Accept-Language",
			"locale:",
		)
	) {
		LeakWarning.warn("locale", false);
	}
	// Manual geolocation and timezone setting
	if (isDomainSet(config, "geolocation:", "timezone")) {
		LeakWarning.warn("geolocation", false);
	}
	// Manual User-Agent setting
	if (isDomainSet(config, "headers.User-Agent")) {
		LeakWarning.warn("header-ua", false);
	}
	// Manual navigator setting
	if (isDomainSet(config, "navigator.")) {
		LeakWarning.warn("navigator", false);
	}
	// Touchscreen digitizer spoofing. Called out separately from the blanket
	// navigator warning because the knock-on effects reach past navigator into
	// CSS pointer media queries and the TouchEvent interfaces.
	if (isDomainSet(config, "navigator.maxTouchPoints")) {
		LeakWarning.warn("max_touch_points", false);
	}
	if (isTruthy(config.instantAnimations)) {
		LeakWarning.warn("instant_animations", false);
	}
	// Manual screen/window setting
	if (isDomainSet(config, "screen.", "window.", "document.body.")) {
		LeakWarning.warn("viewport", false);
	}
}

const WINDOW_DIM_KEYS = [
	"window.outerWidth",
	"window.outerHeight",
	"window.innerWidth",
	"window.innerHeight",
];

/** The CAMOU_CONFIG chunks of a set of launch options, reassembled in order. */
export function camouConfigBlob(fromOptions: Record<string, any>): string {
	const env: Record<string, any> = fromOptions.env ?? {};
	return Object.entries(env)
		.filter(([k]) => k.startsWith("CAMOU_CONFIG_"))
		.map(
			([k, v]) =>
				[
					Number.parseInt(k.slice(k.lastIndexOf("_") + 1), 10),
					String(v),
				] as const,
		)
		.sort((a, b) => a[0] - b[0])
		.map(([, v]) => v)
		.join("");
}

/**
 * The core count the browser must be pinned to for these launch options, or
 * null: the identity's navigator.hardwareConcurrency when this host can honour
 * it (see cpu_affinity), so a page measuring parallelism sees the reported
 * number.
 */
export function pinnedCoreCount(
	fromOptions: Record<string, any>,
): number | null {
	const blob = camouConfigBlob(fromOptions);
	if (!blob || !cpuAffinity.supported()) return null;
	let value: unknown;
	try {
		const parsed = JSON.parse(blob);
		value =
			parsed && typeof parsed === "object" && !Array.isArray(parsed)
				? parsed["navigator.hardwareConcurrency"]
				: undefined;
	} catch {
		return null;
	}
	// The host's count, not this process's live mask: a concurrent pinned
	// launch narrows that while its browser spawns.
	const cores = cpuAffinity.hostCoreCount();
	if (
		typeof value === "number" &&
		Number.isInteger(value) &&
		value >= 1 &&
		value < cores
	) {
		return value;
	}
	return null;
}

/**
 * PID of the process that will spawn the browser (its children inherit the
 * CPU affinity set on it). Python's driver is a separate Node process;
 * playwright-core runs in this one.
 */
export function driverPid(): number {
	return process.pid;
}

/**
 * Whether the CAMOU_CONFIG in a set of launch options spoofs any window
 * dimension. The config is chunked across CAMOU_CONFIG_<n> env vars, so
 * reassemble it in index order before looking.
 */
export function spoofsWindowDimensions(
	fromOptions: Record<string, any>,
): boolean {
	const blob = camouConfigBlob(fromOptions);
	if (!blob) return false;
	return WINDOW_DIM_KEYS.some((key) => blob.includes(key));
}

/**
 * Playwright emulates four media features on every context it creates, whether
 * or not the caller asked: `colorScheme` defaults to "light" and reducedMotion /
 * forcedColors / contrast to their no-preference values. That is an override,
 * not a passthrough -- the page then reports it whatever the host is set to. The
 * JS API's `null` (Python's "no-override") is Playwright's own opt-out: it sends
 * no emulation at all and the browser answers from the host.
 */
export const STOCK_MEDIA_DEFAULTS = {
	colorScheme: null,
	reducedMotion: null,
	forcedColors: null,
	contrast: null,
} as const;

/** Fill STOCK_MEDIA_DEFAULTS into any media option the caller left unset. */
export function withStockMediaDefaults(
	opts: Record<string, any>,
): Record<string, any> {
	const out = { ...opts };
	for (const [option, value] of Object.entries(STOCK_MEDIA_DEFAULTS)) {
		if (out[option] === undefined) out[option] = value;
	}
	return out;
}

/**
 * Default newPage()/newContext() to the host's own media features.
 *
 * Explicit colorScheme / reducedMotion / forcedColors / contrast from the caller
 * always wins; this only replaces Playwright's silent defaults.
 */
export function attachStockMediaDefaults<T>(target: T): T {
	for (const name of ["newPage", "newContext"] as const) {
		const original = (target as any)[name];
		if (typeof original !== "function") continue;
		(target as any)[name] = (options?: Record<string, any>, ...rest: any[]) =>
			original.call(target, withStockMediaDefaults(options ?? {}), ...rest);
	}
	return target;
}

/**
 * Warn when newPage()/newContext() asks for isMobile: Camoufox only has desktop
 * identities, and Juggler ignores the option (TargetRegistry.js).
 */
export function attachDesktopOnlyWarning<T>(target: T): T {
	for (const name of ["newPage", "newContext"] as const) {
		const original = (target as any)[name];
		if (typeof original !== "function") continue;
		(target as any)[name] = (options?: Record<string, any>, ...rest: any[]) => {
			if (options?.isMobile || options?.is_mobile)
				LeakWarning.warn("is_mobile");
			return original.call(target, options, ...rest);
		};
	}
	return target;
}

/**
 * Normalise a context-options object onto the JS API's `viewport: null`,
 * defaulting to it when the caller expressed no preference. Playwright-Python
 * takes `no_viewport=True`; a caller-supplied `noViewport` is accepted and
 * translated.
 */
export function applyNoViewport(
	opts: Record<string, any>,
): Record<string, any> {
	const out = { ...opts };
	if ("noViewport" in out) {
		const noViewport = out.noViewport;
		delete out.noViewport;
		if (noViewport && !("viewport" in out)) out.viewport = null;
		return out;
	}
	if (!("viewport" in out)) out.viewport = null;
	return out;
}

/**
 * Default newPage()/newContext() to no viewport.
 *
 * Playwright applies a 1280x720 viewport by default, which makes Juggler ask
 * the content window to become 1280x720 (TargetRegistry.updateViewportSize).
 * When Camoufox is pinning the window to a spoofed size, that request can
 * never be satisfied, and awaitViewportDimensions has no timeout -- so the
 * second newPage() hangs forever (daijro/camoufox#666). An explicit viewport
 * from the caller always wins.
 */
export function attachNoViewportDefault<T>(target: T): T {
	for (const name of ["newPage", "newContext"] as const) {
		const original = (target as any)[name];
		if (typeof original !== "function") continue;
		(target as any)[name] = (options?: Record<string, any>, ...rest: any[]) =>
			original.call(target, applyNoViewport(options ?? {}), ...rest);
	}
	return target;
}

/**
 * Attaches the virtual display to the browser's cleanup. (Python has an async
 * and a sync variant; playwright-core has one API.)
 */
export function attachVirtualDisplay<T>(
	browser: T,
	virtualDisplay?: VirtualDisplay | null,
): T {
	if (!virtualDisplay) return browser; // Skip if no virtual display is provided

	const target = browser as any;
	const originalClose = target.close.bind(target);

	target.close = async (...args: any[]) => {
		try {
			return await originalClose(...args);
		} finally {
			virtualDisplay.kill();
		}
	};
	// close() never runs on an unexpected disconnect/close, so wire teardown
	// directly too; kill() is idempotent.
	target.on?.(target.contexts ? "disconnected" : "close", () =>
		virtualDisplay.kill(),
	);
	target._virtualDisplay = virtualDisplay;

	return browser;
}

/**
 * The version of the build about to be launched.
 *
 * installedVerStr() answers "which release did `camoufox fetch` put in the
 * cache", which is the wrong question when the caller named a binary. Firefox
 * writes application.ini beside the executable, so when a path is given the
 * answer is right there. Falls back to the installed release when it is not.
 */
export function resolveVerstr(executablePath?: string | null): string {
	if (executablePath) {
		const ini = path.join(path.dirname(executablePath), "application.ini");
		try {
			for (const line of fs.readFileSync(ini, "utf-8").split(/\r\n|\r|\n/)) {
				if (line.startsWith("Version=")) {
					const version = line.split("=").slice(1).join("=").trim();
					if (version) return version;
				}
			}
		} catch {
			// fall through
		}
	}
	return utilsDeps.installedVerStr();
}

/** A bound on the screen a generated fingerprint may claim. */
export type ScreenConstraint =
	| Screen
	| {
			min_width?: number;
			max_width?: number;
			min_height?: number;
			max_height?: number;
			minWidth?: number;
			maxWidth?: number;
			minHeight?: number;
			maxHeight?: number;
	  };

function toScreen(screen: ScreenConstraint): Screen {
	if (screen instanceof Screen) return screen;
	const s = screen as Record<string, number | undefined>;
	return new Screen({
		minWidth: s.minWidth ?? s.min_width,
		maxWidth: s.maxWidth ?? s.max_width,
		minHeight: s.minHeight ?? s.min_height,
		maxHeight: s.maxHeight ?? s.max_height,
	});
}

export interface LaunchOptions {
	/** Camoufox properties to use.
	 * (read https://github.com/daijro/camoufox/blob/main/README.md) */
	config?: Record<string, any>;
	/** Operating system to use for the fingerprint generation. Can be
	 * "windows", "macos", "linux", or a list to randomly choose from. */
	os?: ListOrString;
	/** Whether to block all images. */
	block_images?: boolean;
	/** Whether to block WebRTC entirely. */
	block_webrtc?: boolean;
	/** Whether to block WebGL. To prevent leaks, only use this for special cases. */
	block_webgl?: boolean;
	/** Disables the Cross-Origin-Opener-Policy, allowing elements in cross-origin
	 * iframes, such as the Turnstile checkbox, to be clicked. */
	disable_coop?: boolean;
	/** Use a specific WebGL vendor/renderer pair, as [vendor, renderer]. */
	webgl_config?: [string, string];
	/** Calculate longitude, latitude, timezone, country, & locale based on the IP
	 * address. Pass the target IP address to use, or `true` to find it. */
	geoip?: string | boolean;
	/** Name of the GeoIP database to use (e.g. "MaxMind GeoLite2"). */
	geoip_db?: string;
	/** Humanize the cursor movement: `true`, or the MAX duration in seconds. */
	humanize?: boolean | number;
	/** Locale(s) to use. The first listed locale is used for the Intl API. */
	locale?: string | string[];
	/** List of Firefox addons to use (paths to extracted addons). */
	addons?: string[];
	/** Fonts to load into Camoufox (in addition to the target `os`'s). */
	fonts?: string[];
	/** If enabled, OS-specific system fonts will not be passed to Camoufox. */
	custom_fonts_only?: boolean;
	/** Default addons to exclude. */
	exclude_addons?: DefaultAddon[];
	/** Constrains the screen dimensions of the generated fingerprint. */
	screen?: ScreenConstraint;
	/** Set a fixed window size instead of generating a random one. */
	window?: [number, number];
	/** Use a custom fpgen fingerprint. */
	fingerprint?: Record<string, any>;
	/** Opt into real fingerprint presets: `true` for a random bundled preset,
	 * or a preset object. */
	fingerprint_preset?: boolean | Record<string, any>;
	/** Firefox version to use. Defaults to the current Camoufox version. */
	ff_version?: number;
	/** Whether to run the browser in headless mode. Defaults to false. */
	headless?: boolean;
	/** Whether to enable running scripts in the main world ("mw:" prefix). */
	main_world_eval?: boolean;
	/** Whether to allow addons to open new tabs. Defaults to false. */
	allow_addon_new_tab?: boolean;
	/** Custom Camoufox browser executable path. */
	executable_path?: string;
	/** Select a specific installed browser version ("official/beta.20",
	 * "beta.20", "134.0.2-beta.20"). Defaults to the active version. */
	browser?: string;
	/** Firefox user preferences to set. */
	firefox_user_prefs?: Record<string, any>;
	/** Proxy to use for the browser. */
	proxy?: ProxyConfig;
	/** Cache previous pages, requests, etc (uses more memory). */
	enable_cache?: boolean;
	/** Arguments to pass to the browser. */
	args?: string[];
	/** Environment variables to set. Defaults to a copy of process.env. */
	env?: EnvVars;
	/** Suppress leak warnings for options you are deliberately overriding. */
	i_know_what_im_doing?: boolean;
	/** Prints the config being sent to Camoufox. */
	debug?: boolean;
	/** Virtual display number, e.g. ":99". Handled by Camoufox & NewBrowser. */
	virtual_display?: string;
	/** Pin the browser to navigator.hardwareConcurrency cores (Linux/Windows).
	 * OFF by default -- it costs real CPU and serializes concurrent launches. */
	pin_cpu_cores?: boolean;
	/** Additional Firefox launch options, passed straight through to Playwright. */
	[key: string]: any;
}

/**
 * Builds the Playwright Firefox launch options for Camoufox.
 *
 * Accepts all Playwright Firefox launch options, along with the Camoufox ones
 * documented on {@link LaunchOptions}.
 */
export async function launchOptions({
	config,
	os: targetOsOption,
	block_images,
	block_webrtc,
	block_webgl,
	disable_coop,
	webgl_config,
	geoip,
	geoip_db,
	humanize,
	locale,
	addons,
	fonts,
	custom_fonts_only,
	exclude_addons,
	screen,
	window,
	fingerprint,
	fingerprint_preset,
	ff_version,
	headless,
	main_world_eval,
	allow_addon_new_tab,
	executable_path,
	browser,
	firefox_user_prefs,
	proxy,
	enable_cache,
	args,
	env,
	i_know_what_im_doing,
	debug,
	virtual_display,
	pin_cpu_cores,
	...passthrough
}: LaunchOptions = {}): Promise<Record<string, any>> {
	utilsDeps.ensureBrowserProfileDir(env);

	// Build the config
	config ??= {};

	// Set default values for optional arguments
	headless ??= false;
	addons ??= [];
	args ??= [];
	firefox_user_prefs ??= {};
	custom_fonts_only ??= false;
	i_know_what_im_doing ??= false;
	// Keep per-launch overrides isolated from the process environment and from
	// mappings supplied by callers. In particular, DISPLAY must not outlive the
	// virtual display that owns it.
	env = env == null ? ({ ...process.env } as EnvVars) : { ...env };
	if (executable_path == null) {
		// Point every launch at a specific build without threading the path
		// through each call site. Absent the variable nothing changes.
		const envExecutable = (process.env.CAMOUFOX_EXECUTABLE_PATH ?? "").trim();
		if (envExecutable) {
			executable_path = envExecutable;
		}
	}
	if (typeof executable_path === "string") {
		executable_path = path.resolve(executable_path);
	}

	// Handle virtual display
	if (virtual_display) {
		env.DISPLAY = virtual_display;
		// Virtual display uses Xvfb (X11). If the host session forces Wayland via
		// env vars, GTK/Firefox may try Wayland and ignore DISPLAY.
		env.GDK_BACKEND = "x11";
		delete env.WAYLAND_DISPLAY;
		env.MOZ_ENABLE_WAYLAND = "0";
	}

	// Warn the user for manual config settings
	if (!i_know_what_im_doing) {
		warnManualConfig(config);
	}

	// Snapshot which domains the USER set before fingerprint generation fills in
	// the rest. The post-generation corrections below must only touch generated
	// values, never override what the user passed.
	const userSetNavigator = isDomainSet(config, "navigator.");
	const userSetScreenWindow = isDomainSet(config, "screen.", "window.");
	const userSetMediaDevices = isDomainSet(config, "mediaDevices:");
	const userSetFonts = Boolean(fonts?.length) || isDomainSet(config, "fonts");
	const userSetVoices = isDomainSet(config, "voices");
	const userSetDnt = "navigator.doNotTrack" in config;
	const userSetGpc = "navigator.globalPrivacyControl" in config;
	const userSetAcceptEncoding = "headers.Accept-Encoding" in config;
	const userSetAudioSeed = "audio:seed" in config;

	// The salt that makes every seeded draw belong to this identity (see
	// fingerprints.identitySalt): stable when the caller pinned the identity --
	// a fingerprint, a preset object, or their own config naming the UA -- and
	// fresh otherwise.
	let salt: bigint | number;
	if (fingerprint != null) {
		salt = utilsDeps.identitySalt(fingerprint);
	} else if (isPlainObject(fingerprint_preset)) {
		salt = utilsDeps.identitySalt(fingerprint_preset);
	} else if ("navigator.userAgent" in config) {
		salt = utilsDeps.identitySalt({ ...config });
	} else {
		salt = utilsDeps.identitySalt();
	}

	// Assert the target OS is valid
	if (isTruthy(targetOsOption)) {
		checkValidOs(targetOsOption as ListOrString);
	} else if (isTruthy(webgl_config)) {
		// webgl_config requires OS to be set
		throw new ValueError("OS must be set when using webgl_config");
	}

	// Add the default addons
	await utilsDeps.addDefaultAddons(addons, exclude_addons);

	// Confirm all addon paths are valid
	if (addons.length) {
		utilsDeps.confirmPaths(addons);
		config.addons = addons;
	}

	// The managed install is resolved lazily in Python (camoufox_path() may
	// download); here that download is async, so do it before any sync lookup.
	if (!executable_path) {
		await utilsDeps.ensureCamoufoxInstalled();
	}

	// Get the Firefox version
	let ffVersionStr: string;
	if (ff_version) {
		ffVersionStr = String(ff_version);
		LeakWarning.warn("ff_version", i_know_what_im_doing);
	} else {
		ffVersionStr = resolveVerstr(executable_path).split(".")[0];
	}

	// Generate a fingerprint
	let usedPreset = false;
	if (fingerprint != null) {
		// User passed a custom fingerprint
		if (!i_know_what_im_doing) {
			checkCustomFingerprint(fingerprint);
		}
	} else if (isTruthy(fingerprint_preset)) {
		// User opted into real fingerprint presets
		const preset = isPlainObject(fingerprint_preset)
			? fingerprint_preset
			: await utilsDeps.getRandomPreset(targetOsOption, ffVersionStr);
		if (isTruthy(preset)) {
			mergeInto(
				config,
				await utilsDeps.fromPreset(preset as any, ffVersionStr, salt),
			);
			usedPreset = true;
		}
	}

	// Bound the geometry to the real display. The generator only honours this
	// when its pool has a match, so it is re-applied after generation as well.
	// `headless` and "is there a display to probe" are separate questions.
	const screenCons: Screen | null = screen
		? toScreen(screen)
		: utilsDeps.hasDisplay(env)
			? utilsDeps.getScreenCons(headless)
			: null;

	if (!usedPreset && fingerprint == null) {
		// Default: synthetic generation via fpgen (infinite unique fingerprints)
		fingerprint = await utilsDeps.generateFingerprint({
			screen: screenCons ?? undefined,
			window,
			os: targetOsOption,
		});
	}

	if (!usedPreset && fingerprint != null) {
		// Inject the generated fingerprint into the config
		mergeInto(config, utilsDeps.fromFpgen(fingerprint, ffVersionStr));
	}

	const targetOs = getTargetOs(config);

	// A preset whose screen is a phone viewport is not a real desktop device.
	if (!userSetScreenWindow && coherence.screenIsImplausible(config)) {
		coherence.repairScreenOrientation(config);
		utilsDeps.raiseScreenToModernFloor(config);
	}

	// Correct fingerprint inconsistencies that leak as headless /
	// impossible-geometry tells, unless the user is driving these themselves.
	if (!userSetNavigator) {
		utilsDeps.fixNavigatorArch(config, targetOs);
		utilsDeps.fixHardwareConcurrency(config, Boolean(pin_cpu_cores));
	}
	if (!userSetScreenWindow) {
		// Lift netbook-era geometry to something current hardware reports,
		// before the display clamp below so a genuinely small real monitor still
		// wins (#729). Synthetic draws only: a preset is a real device.
		if (!usedPreset) {
			utilsDeps.raiseScreenToModernFloor(config);
		}
		// Headful on a real monitor only: this bound exists so the window fits
		// the screen it is drawn on. headless has no window to overflow, and
		// headless="virtual" reaches here as headless=false with a 1x1 Xvfb.
		if (headless === false && !virtual_display && screenCons) {
			utilsDeps.clampScreenToDisplay(
				config,
				screenCons.maxWidth as number,
				screenCons.maxHeight as number,
			);
		}
		utilsDeps.fixScreenNoTaskbar(config, targetOs);
		utilsDeps.clampWindowDimensions(config);
		utilsDeps.clampWindowPosition(config);
	}

	// Deliberately NOT setting window.history.length: settings/camoufox.cfg runs
	// Firefox's stock max_entries, so the real value starts at 1 and grows with
	// each navigation; pinning it would contradict history.back().

	// Update fonts list
	if (fonts?.length) {
		config.fonts = fonts;
	}

	if (custom_fonts_only) {
		firefox_user_prefs["gfx.bundled-fonts.activate"] = 0;
		if (fonts?.length) {
			LeakWarning.warn("custom_fonts_only");
		} else {
			throw new ValueError(
				"No custom fonts were passed, but `custom_fonts_only` is enabled.",
			);
		}
	} else if (!userSetFonts || !isTruthy(config.fonts)) {
		// Draw the font subset HERE, after every identity fix-up above, so the
		// seed sees the final UA/screen/cores/GPU: the same presented identity
		// always gets the same font list (#442/#765).
		const osName =
			({ win: "windows", mac: "macos", lin: "linux" } as const)[targetOs] ??
			"macos";
		try {
			config.fonts = utilsDeps.generateRandomFontSubset(
				osName,
				utilsDeps.identitySeed(config, salt),
				// host's own OS on macOS/Windows: the real system fonts are used
				// (font-hijacker.patch keeps the bundle inactive), so only the OS
				// base is claimed
				(targetOs === "mac" || targetOs === "win") &&
					utilsDeps.hostOsKey() === targetOs,
			);
		} catch (e) {
			if (!isPyError(e, "OSError", "ValueError")) throw e;
			FallbackWarning.warn(
				"Drawing the font list",
				`every font fonts.json lists for ${targetOs}`,
				e,
				config["navigator.userAgent"],
			);
			updateFonts(config, targetOs);
		}
	}

	// Draw the identity's media devices unless the caller set any mediaDevices:
	// key. An empty enumerateDevices() list is a headless tell; a wrong label
	// after a grant is a spoof tell.
	if (!userSetMediaDevices) {
		await utilsDeps.setMediaDevicesDefaults(config, salt);
	}

	// Scrollbars: pin the look-and-feel to the claimed OS so headless == headed
	// == stock, and for Windows to the version the identity's font draw
	// presents (Win11 fonts with classic scrollbars is a pair no real machine
	// produces).
	if (targetOs === "win") {
		const presentedFonts: string[] = config.fonts || [];
		const windows11 =
			!presentedFonts.length ||
			presentedFonts.some((font) => WINDOWS_11_MARKER_FONTS.has(font));
		setInto(firefox_user_prefs, "ui.useOverlayScrollbars", windows11 ? 1 : 0);
	} else {
		setInto(firefox_user_prefs, "ui.useOverlayScrollbars", 1);
	}

	// Per-character font fallback, LINUX ONLY: with async fallback on, the
	// first measurement of a character only one bundled family provides returns
	// the primary family's .notdef. macOS must NOT get this.
	if (targetOs === "lin") {
		setInto(firefox_user_prefs, "gfx.font_rendering.fallback.async", false);
	}

	// Storage quota, from the host's own disk (see stockProfileDiskCapacityKb).
	const quotaLimitKb = utilsDeps.stockProfileDiskCapacityKb();
	if (quotaLimitKb) {
		setInto(firefox_user_prefs, QUOTA_FIXED_LIMIT_PREF, quotaLimitKb);
	}

	// navigator.doNotTrack and navigator.globalPrivacyControl are pref-backed in
	// Firefox; spoofing them anywhere else leaves the wire (or the worker)
	// contradicting the API (daijro/camoufox#760). A stock Firefox 152 reports
	// "unspecified" and false, so generated values are dropped unless the
	// caller set them explicitly. screen.colorDepth is left as drawn.
	if (!userSetDnt) {
		delete config["navigator.doNotTrack"];
	}
	if (!userSetGpc) {
		delete config["navigator.globalPrivacyControl"];
	}
	const dnt = config["navigator.doNotTrack"];
	firefox_user_prefs["privacy.donottrackheader.enabled"] =
		dnt != null && pyStr(dnt) === "1";
	const gpc = config["navigator.globalPrivacyControl"];
	firefox_user_prefs["privacy.globalprivacycontrol.enabled"] =
		gpc != null ? isTruthy(gpc) : false;

	// Accept-Encoding: Firefox's own value is already what the identity claims,
	// so the generated header is dropped unless the caller set it.
	if (!userSetAcceptEncoding) {
		delete config["headers.Accept-Encoding"];
	}

	// The audio noise seed follows the identity: a returning "same device" must
	// reproduce its audio hash (#442/#765). Never 0 (0 disables the noise).
	// There is no canvas seed: the browser adds no canvas noise (#528), and no
	// glyph-spacing noise either (ci/tribal-rules.yml: no-glyph-spacing-noise).
	if (!userSetAudioSeed) {
		config["audio:seed"] = audioSeedFromIdentity(
			utilsDeps.identitySeed(config, salt),
		);
	}

	// Set geolocation
	if (isTruthy(geoip)) {
		geoipAllowed(); // Assert that geoip is allowed

		let geoipIp: string;
		if (geoip === true) {
			// Find the user's IP address
			geoipIp = proxy
				? await utilsDeps.publicIp(ProxyHelper.asString(proxy))
				: await utilsDeps.publicIp();
		} else {
			geoipIp = geoip as string;
		}

		// Spoof WebRTC if not blocked
		if (!block_webrtc) {
			if (validIPv4(geoipIp)) {
				setInto(config, "webrtc:ipv4", geoipIp);
				firefox_user_prefs["network.dns.disableIPv6"] = true;
			} else if (validIPv6(geoipIp)) {
				setInto(config, "webrtc:ipv6", geoipIp);
			}
		}

		const geolocation = await utilsDeps.getGeolocation(geoipIp, geoip_db);
		for (const [key, value] of Object.entries(geolocation.asConfig())) {
			if (
				[
					"timezone",
					"locale:language",
					"locale:region",
					"locale:script",
				].includes(key)
			) {
				setInto(config, key, value);
			} else {
				config[key] = value;
			}
		}
	}

	// A page that receives a position without a prompt must also see
	// permissions.query({name: 'geolocation'}) report "granted" (#769).
	if ("geolocation:latitude" in config && "geolocation:longitude" in config) {
		setInto(firefox_user_prefs, "permissions.default.geo", 1);
	} else if (
		// Raise a warning when a proxy is being used without spoofing
		// geolocation. This warning cannot be ignored with i_know_what_im_doing.
		isTruthy(proxy) &&
		!(proxy?.server ?? "").includes("localhost") &&
		!isDomainSet(config, "geolocation")
	) {
		LeakWarning.warn("proxy_without_geoip");
	}

	// Set locale
	if (isTruthy(locale)) {
		await handleLocales(locale as string | string[], config);
	}

	// Select the browser's UI locale to match the Intl locale. Always set: an
	// EMPTY value would follow the host OS locale.
	let requested: string;
	if (isTruthy(config["locale:language"])) {
		requested = [
			config["locale:language"],
			config["locale:script"],
			config["locale:region"],
		]
			.filter((part) => isTruthy(part))
			.join("-");
	} else {
		requested = "en-US";
	}
	setInto(firefox_user_prefs, "intl.locale.requested", requested);

	// Spoof the speech-synthesis voice list. This has to fail CLOSED: leaving
	// `voices` unset exposes every native voice on the box (#731). Drawn after
	// the locale is resolved: the Windows voice list is the display language's
	// pack.
	if (!userSetVoices || !("voices" in config)) {
		const osNameV =
			({ win: "windows", mac: "macos", lin: "linux" } as const)[targetOs] ??
			"macos";
		let voiceLocale = config["navigator.language"];
		if (isTruthy(config["locale:language"])) {
			voiceLocale = [config["locale:language"], config["locale:region"]]
				.filter((part) => isTruthy(part))
				.join("-");
		}
		try {
			config.voices = utilsDeps.generateRandomVoiceSubset(
				osNameV,
				voiceLocale ?? null,
				utilsDeps.identitySeed(config, salt),
			);
		} catch (e) {
			if (!isPyError(e, "OSError", "ValueError", "KeyError")) throw e;
			// An empty list still blocks the host's voices (see below), so a
			// generation failure degrades to "no voices" rather than "all of
			// the host's".
			FallbackWarning.warn(
				"Drawing the speech voices",
				"no speech voices",
				e,
				config["navigator.userAgent"],
			);
			config.voices = [];
		}
	}

	// Pin the block explicitly instead of relying on a non-empty list to imply
	// it. setInto leaves an explicit caller value alone.
	setInto(config, "voices:blockIfNotDefined", true);

	// Pass the humanize option
	if (isTruthy(humanize)) {
		setInto(config, "humanize", true);
		// MaskConfig expects maxTime to be a JSON number.
		// float(humanize): a JSON number with a floating-point representation.
		if (typeof humanize === "number") {
			setInto(config, "humanize:maxTime", new PyFloat(humanize));
		}
	}

	// Enable the main world context creation
	if (main_world_eval) {
		setInto(config, "allowMainWorld", true);
	}

	// Allow addon open new tabs
	if (allow_addon_new_tab) {
		setInto(config, "allowAddonNewtab", true);
	}

	// Set Firefox user preferences
	if (block_images) {
		LeakWarning.warn("block_images", i_know_what_im_doing);
		firefox_user_prefs["permissions.default.image"] = 2;
	}
	if (block_webrtc) {
		firefox_user_prefs["media.peerconnection.enabled"] = false;
	}
	if (disable_coop) {
		LeakWarning.warn("disable_coop", i_know_what_im_doing);
		firefox_user_prefs["browser.tabs.remote.useCrossOriginOpenerPolicy"] =
			false;
	}
	// A persistent context takes its context options here.
	if (passthrough.is_mobile || passthrough.isMobile) {
		LeakWarning.warn("is_mobile", i_know_what_im_doing);
	}

	// Drop values the source supplied that this identity cannot keep, before the
	// WebGL pool below defers to them. Here, not earlier, because the check
	// reads the core count and the screen, which the launch replaces above.
	coherence.dropIncoherentSourceValues(config, targetOs);

	if (block_webgl) {
		firefox_user_prefs["webgl.disabled"] = true;
		LeakWarning.warn("block_webgl", i_know_what_im_doing);
	} else {
		let webglFp: Record<string, any>;
		const seed = () =>
			utilsDeps.identitySeed(config as Record<string, any>, salt);
		// A pair the caller named, or the preset's own GPU, keeps its name and
		// gets that device's recorded parameters. webglForGpu raises for a GPU
		// fpgen has never seen: the caller asked for something that does not exist.
		if (isTruthy(webgl_config)) {
			const [vendor, renderer] = webgl_config as [string, string];
			webglFp = await utilsDeps.webglForGpu(targetOs, vendor, renderer, seed());
		} else if (
			isTruthy(config["webGl:vendor"]) &&
			isTruthy(config["webGl:renderer"])
		) {
			webglFp = await utilsDeps.webglForGpu(
				targetOs,
				config["webGl:vendor"],
				config["webGl:renderer"],
				seed(),
			);
		} else {
			// Synthetic path: keep the GPU coherent with the screen fpgen already
			// picked. Sampling the two independently yields pairs no real machine
			// ships -- a discrete desktop GPU behind a 1024x600 panel (#729).
			webglFp = await utilsDeps.sampleWebglForScreen(
				targetOs,
				config["screen.width"],
				config["screen.height"],
				seed(),
				config["navigator.hardwareConcurrency"],
			);
		}
		const enableWebgl2 = webglFp.webGl2Enabled;
		delete webglFp.webGl2Enabled;

		// Merge the WebGL fingerprint into the config
		mergeInto(config, webglFp);
		// Set the WebGL preferences
		mergeInto(firefox_user_prefs, {
			"webgl.enable-webgl2": enableWebgl2,
			"webgl.force-enabled": true,
		});
	}

	// Every identity passes the whole-identity checks, whatever built it. The
	// pools are sampled independently, so a machine that never existed can be
	// assembled from parts that are each fine on their own. See coherence.ts.
	const incoherent = coherence.apply(config, targetOs);
	if (incoherent.length && debug) {
		for (const violation of incoherent) {
			console.log(
				`Incoherent identity (${violation.rule}): ${violation.detail}`,
			);
		}
	}

	// Cache previous pages, requests, etc (uses more memory)
	if (enable_cache) {
		mergeInto(firefox_user_prefs, CACHE_PREFS);
	}

	// Print the config if debug is enabled
	if (debug) {
		console.log("[DEBUG] Config:");
		console.log(inspect(config, { depth: null, sorted: true }));
	}

	// Validate the config
	warnIfExecutablePredatesPlaywright(executable_path);
	utilsDeps.validateConfig(config, executable_path);

	// Prepare environment variables to pass to Camoufox
	const envVars: EnvVars = {
		...utilsDeps.getEnvVars(config, targetOs, executable_path),
		...getPrefEnvVars(firefox_user_prefs),
		...env,
	};

	// Prepare the executable path
	let resolvedExecutable: string;
	if (executable_path) {
		resolvedExecutable = String(executable_path);
	} else if (browser) {
		// Select a specific installed browser version
		const browserPath = await utilsDeps.findInstalledVersion(browser);
		if (!browserPath) {
			throw new Error(
				`Browser version '${browser}' not found. Run \`camoufox list\` to see installed versions.`,
			);
		}
		resolvedExecutable = utilsDeps.launchPath(browserPath);
	} else {
		resolvedExecutable = utilsDeps.launchPath();
	}

	const result: Record<string, any> = {
		executablePath: resolvedExecutable,
		args,
		env: envVars,
		firefoxUserPrefs: firefox_user_prefs,
		headless,
		...passthrough,
	};
	// Only include proxy if it's set (Playwright validates this)
	// https://github.com/coryking/camoufox/commit/1336e8e509e8c12a896a09d9ee51f131f739f106
	// Thanks @coryking
	if (proxy != null) {
		result.proxy = proxy;
	}

	return result;
}

/** Python truthiness for the option values launch_options() tests. */
function isTruthy(value: unknown): boolean {
	if (value === null || value === undefined || value === false) return false;
	if (value === 0 || value === "" || Number.isNaN(value)) return false;
	if (Array.isArray(value)) return value.length > 0;
	if (typeof value === "object") return Object.keys(value as object).length > 0;
	return true;
}

function isPlainObject(value: unknown): value is Record<string, any> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}
