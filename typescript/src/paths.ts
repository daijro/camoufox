/**
 * Platform constants, install paths and the bundled data files. A leaf of the
 * module graph: pkgman.ts and multiversion.ts import each other, and both need
 * these values while they are still being evaluated.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { setModelDir } from "fpgen-js";
import { parse as parseYaml } from "yaml";
import { PRODUCT } from "./product.js";

export { rprint, style } from "camoucore/download.js";
export { ARCH_MAP, OS_MAP, OS_NAME } from "camoucore/host.js";

export const INSTALL_DIR: string = PRODUCT.cacheDir;

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
	x86IntelShare: number;
	cpuIdentityPref: Record<"x86/intel" | "x86/amd" | "arm", number>;
	cpuManufacturers: Record<
		"mac" | "windows" | "linux",
		Record<"x86" | "arm", string[]>
	>;
	intelOnlyCoreCounts: number[];
	appleSiliconPanels: Record<string, [number, number][]>;
	intelMacIgpCores: number[];
	intelMacDgpuExtraCores: number[];
	plausibleDpr: Record<string, number[]>;
	macNoveltyVoices: string[];
	macEloquenceVoices: string[];
	baselineTaskbarHeight: Record<"win" | "mac" | "lin", number>;
	baselineMultiTouchPoints: number;
	cachePrefs: Record<string, any>;
	windowsBehaviourPrefs: Record<string, any>;
}
export const LAUNCHER_CONSTANTS: Readonly<LauncherConstants> = loadDataFile(
	"launcher-constants.json",
);

// Camoufox keeps the fpgen model in its cache, beside the browsers.
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
