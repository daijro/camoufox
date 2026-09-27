/**
 * Shared scaffolding for the launch-layer tests: a scratch camoufox cache
 * (XDG_CACHE_HOME, set before any src module is imported -- INSTALL_DIR is
 * computed at import time), the fixture browser bundle, and the counterpart
 * of the Python tests' `isolated_launch_dependencies` fixture.
 *
 * Import this module FIRST, then import src modules dynamically.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FIXTURES = path.join(HERE, "fixtures", "launch");
export const BUNDLE = path.join(FIXTURES, "bundle");
export const BUNDLE_EXE = path.join(BUNDLE, "camoufox-bin");

// Keep reading the real fpgen model: it lives in the real cache, which the
// scratch XDG_CACHE_HOME below would otherwise hide.
if (!process.env.CAMOUFOX_FPGEN_DATA) {
	const xdg = process.env.XDG_CACHE_HOME?.trim();
	const base = xdg ? xdg : path.join(os.homedir(), ".cache");
	process.env.CAMOUFOX_FPGEN_DATA = path.join(base, "camoufox", "fpgen");
}

export const SCRATCH = fs.mkdtempSync(
	path.join(os.tmpdir(), "camoufox-launch-test-"),
);
process.env.XDG_CACHE_HOME = path.join(SCRATCH, "xdg-cache");
export const CACHE = path.join(SCRATCH, "xdg-cache", "camoufox");
export const HOME = path.join(SCRATCH, "home");
fs.mkdirSync(HOME, { recursive: true });

// The default addon, already "downloaded", so nothing is fetched.
fs.mkdirSync(path.join(CACHE, "addons", "UBO"), { recursive: true });
fs.writeFileSync(path.join(CACHE, "addons", "UBO", "manifest.json"), "{}");

export const utils = await import("../src/utils.js");
export const fingerprints = await import("../src/fingerprints.js");
export const warnings = await import("../src/warnings.js");

/** Reassemble the chunked CAMOU_CONFIG_<n> env vars into the config. */
export function configOf(options: Record<string, any>): Record<string, any> {
	const blob = utils.camouConfigBlob(options);
	return JSON.parse(blob);
}

const deps = utils.utilsDeps;
const ORIGINAL = { ...deps };

/** Put every injection point back. */
export function restoreDeps(): void {
	Object.assign(deps, ORIGINAL);
}

/** The host every launch test runs against: no display, a fixed disk. */
export function stubHost(): void {
	deps.hasDisplay = () => false;
	deps.getScreenCons = () => null;
	deps.stockProfileDiskCapacityKb = () => 250_000_000;
	deps.ensureCamoufoxInstalled = async () => BUNDLE;
	deps.installedVerStr = () => "152.0.4-beta.31";
	deps.launchPath = (() => BUNDLE_EXE) as any;
	deps.getPath = ((file: string) => path.join(BUNDLE, file)) as any;
}

/**
 * pythonlib/tests' `isolated_launch_dependencies`: launchOptions() reduced to
 * environment assembly -- no fingerprint, fonts, voices, geometry fixes,
 * validation or env generation.
 */
export function isolateLaunch(): void {
	stubHost();
	deps.addDefaultAddons = async () => undefined;
	deps.generateFingerprint = async () => ({});
	deps.fromFpgen = () => ({});
	deps.getScreenCons = () => null;
	deps.generateRandomFontSubset = () => [];
	deps.generateRandomVoiceSubset = () => [];
	deps.fixNavigatorArch = () => undefined;
	deps.fixScreenNoTaskbar = () => undefined;
	deps.clampWindowDimensions = () => undefined;
	deps.setMediaDevicesDefaults = () => undefined;
	deps.validateConfig = () => undefined;
	deps.getEnvVars = () => ({});
}

/** Run `fn` with warnings captured instead of printed. */
export async function quietly<T>(fn: () => Promise<T>): Promise<T> {
	const { result, error } = await warnings.recordWarnings(fn);
	if (error) throw error;
	return result as T;
}
