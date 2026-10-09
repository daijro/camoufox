/**
 * Platform constants, install paths and the bundled data files. A leaf of the
 * module graph: pkgman.ts and multiversion.ts import each other, and both need
 * these values while they are still being evaluated.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { setModelDir } from "fpgen";
import { parse as parseYaml } from "yaml";
import { UnsupportedOS } from "./exceptions.js";

export const ARCH_MAP: Record<string, string> = {
	x64: "x86_64",
	amd64: "x86_64",
	x86: "x86_64",
	ia32: "i686",
	i686: "i686",
	i386: "i686",
	arm64: "arm64",
	aarch64: "arm64",
	arm: "arm64",
};

export const OS_MAP: Record<string, "mac" | "win" | "lin"> = {
	darwin: "mac",
	linux: "lin",
	win32: "win",
};

if (!(process.platform in OS_MAP)) {
	throw new UnsupportedOS(`OS ${process.platform} is not supported`);
}

export const OS_NAME: "mac" | "win" | "lin" = OS_MAP[process.platform];

/**
 * platformdirs' user_cache_dir(appName), reimplemented so the TS and Python
 * launchers share one install directory. Hardcoding ~/.cache would diverge on
 * hosts that set XDG_CACHE_HOME, and on macOS/Windows entirely.
 */
function userCacheDir(appName: string): string {
	if (OS_NAME === "win") {
		const localAppData = process.env.LOCALAPPDATA;
		const base =
			localAppData && path.isAbsolute(localAppData)
				? localAppData
				: path.join(os.homedir(), "AppData", "Local");
		return path.join(base, appName, appName, "Cache");
	}
	if (OS_NAME === "mac") {
		return path.join(os.homedir(), "Library", "Caches", appName);
	}
	// platformdirs: any non-blank XDG_CACHE_HOME is taken as-is.
	const xdg = process.env.XDG_CACHE_HOME ?? "";
	const base = xdg.trim() ? xdg : path.join(os.homedir(), ".cache");
	return path.join(base, appName);
}

export const INSTALL_DIR: string = userCacheDir("camoufox");

/**
 * The data files both launchers read. They live in python/src/camoufox/, the one
 * copy in the repo; `pnpm build` copies them into dist/data-files/ for the npm
 * tarball, so one seed draws one identity in either launcher.
 */
export const DATA_FILES: readonly string[] = [
	"browser-pin.json",
	"essential-fonts.json",
	"fingerprint-presets.json",
	"fingerprint-presets-v150.json",
	"font-bases.json",
	"font-groups.json",
	"fonts.json",
	"fpgen.yml",
	"launcher-constants.json",
	"media-devices.json",
	"repos.yml",
	"territoryInfo.xml",
	"voice-manifests.json",
	"voice-uris.json",
	"warnings.yml",
];

/**
 * Where DATA_FILES are read from: dist/data-files/ in a built package, else
 * python/src/camoufox/ itself when running from src/ in the repo.
 */
export const LOCAL_DATA: string = fs.existsSync(
	path.join(import.meta.dirname, "data-files"),
)
	? path.join(import.meta.dirname, "data-files")
	: path.resolve(import.meta.dirname, "..", "..", "python", "src", "camoufox");

/** A data file (relative to LOCAL_DATA), parsed as YAML or JSON by its extension. */
export function loadDataFile<T = any>(file: string): T {
	const text = fs.readFileSync(path.resolve(LOCAL_DATA, file), "utf-8");
	return (file.endsWith(".yml") ? parseYaml(text) : JSON.parse(text)) as T;
}

/** Values both launchers use, kept in one file (python/src/camoufox/launcher-constants.json). */
export interface LauncherConstants {
	markerFonts: Record<"win" | "mac" | "lin", string[]>;
	windows11MarkerFonts: string[];
	plausibleCoreCounts: number[];
	appleSiliconCores: number[];
	appleSiliconPanels: Record<string, [number, number][]>;
	intelMacIgpCores: number[];
	intelMacDgpuExtraCores: number[];
	plausibleDpr: Record<string, number[]>;
	macNoveltyVoices: string[];
	macEloquenceVoices: string[];
	cachePrefs: Record<string, any>;
}
export const LAUNCHER_CONSTANTS: Readonly<LauncherConstants> = loadDataFile(
	"launcher-constants.json",
);

// Camoufox keeps the fpgen model in its cache, beside the browsers and addons.
setModelDir(process.env.CAMOUFOX_FPGEN_DATA || path.join(INSTALL_DIR, "fpgen"));

export const OS_ARCH_MATRIX: Record<string, string[]> = {
	win: ["x86_64", "i686"],
	mac: ["x86_64", "arm64"],
	lin: ["x86_64", "arm64", "i686"],
};

export const LAUNCH_FILE: Record<string, string> = {
	win: "camoufox.exe",
	mac: "../MacOS/camoufox",
	lin: "camoufox-bin",
};

const ANSI: Record<string, string> = {
	red: "31",
	green: "32",
	yellow: "33",
	blue: "34",
	cyan: "36",
	bright_black: "90",
};

/** click.style: ANSI-styled text, plain when stdout is not a colour terminal. */
export function style(
	text: string,
	{ fg, bold, dim }: { fg?: string | null; bold?: boolean; dim?: boolean } = {},
): string {
	if (!process.stdout.isTTY || process.env.NO_COLOR) return text;
	const codes: string[] = [];
	if (bold) codes.push("1");
	if (dim) codes.push("2");
	if (fg && ANSI[fg]) codes.push(ANSI[fg]);
	return codes.length ? `\x1b[${codes.join(";")}m${text}\x1b[0m` : text;
}

/** Print a bold, optionally coloured message, as the Python twin's `rich` print. */
export function rprint(msg: string, fg?: string, nl: boolean = true): void {
	process.stdout.write(style(msg, { fg, bold: true }) + (nl ? "\n" : ""));
}
