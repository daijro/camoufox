/**
 * Helpers to fetch geolocation, timezone, and locale data given an IP.
 *
 * TypeScript twin of pythonlib/camoufox/geolocation.py. The on-disk layout
 * (geoip/mmdb/<name>-<ipver>.mmdb and geoip/config.yml under the camoufox
 * cache dir) is the Python package's, so both launchers share one database.
 */
import * as fs from "node:fs";
import { createRequire } from "node:module";
import * as os from "node:os";
import * as path from "node:path";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { NotInstalledGeoIPExtra, UnknownIPLocation } from "./exceptions.js";
import { validateIP } from "./ip.js";
import { Geolocation, SELECTOR } from "./locales.js";
import { INSTALL_DIR, LOCAL_DATA } from "./paths.js";
import { loadWarnings, warn } from "./warnings.js";

export const GEOIP_DIR: string = path.join(INSTALL_DIR, "geoip");
export const MMDB_DIR: string = path.join(GEOIP_DIR, "mmdb");
export const GEOIP_CONFIG: string = path.join(GEOIP_DIR, "config.yml");

/** A database whose data was built longer ago than this is refreshed. The
 * default source publishes weekly, so a week and a day catches every release. */
export const UPDATE_DAYS = 8;
/** ...but at most once a day, so a source that stops publishing costs one
 * download a day rather than one per launch. */
export const RECHECK_DAYS = 1;
/** A freshly downloaded build older than this means its source is frozen. */
export const FROZEN_DAYS = 30;

const DAY_MS = 24 * 60 * 60 * 1000;

export interface GeoIPRepo {
	name: string;
	urls: Record<string, string | string[]>;
	paths: Record<string, string>;
	extract?: boolean;
	deprecated?: boolean;
	[key: string]: any;
}

/** A reader over an mmdb file: maxminddb.Reader's `get` and `metadata`. */
export interface MmdbReader {
	get(ip: string): any;
	metadata?: { buildEpoch: Date };
	close?(): void;
}

const require_ = createRequire(import.meta.url);

/**
 * Whether the mmdb reader is available. Python gates this on the optional
 * `maxminddb` import (`pip install camoufox[geoip]`); here it is the optional
 * `maxmind` package.
 */
export function allowGeoip(): boolean {
	try {
		require_.resolve("maxmind");
		return true;
	} catch {
		return false;
	}
}

/**
 * Injection points (tests replace them): opening an mmdb, and downloading.
 */
export const geoipDeps = {
	async openDatabase(mmdbPath: string): Promise<MmdbReader> {
		const maxmind = (await import("maxmind")).default;
		const buffer = fs.readFileSync(mmdbPath);
		return new maxmind.Reader<any>(buffer);
	},
	downloadMmdb: (source?: string) =>
		downloadMmdb(source, undefined, source === undefined),
};

/**
 * Resolve a dotted path in a nested object.
 */
function findIn(data: any, key: string): any {
	for (const part of key.split(".")) {
		if (typeof data !== "object" || data === null || Array.isArray(data)) {
			return null;
		}
		data = data[part];
		if (data === undefined || data === null) {
			return null;
		}
	}
	return data;
}

/**
 * Load GeoIP repos and default name from repos.yml.
 */
function loadGeoipRepos(): [GeoIPRepo[], string] {
	const data =
		(parseYaml(
			fs.readFileSync(path.join(LOCAL_DATA, "repos.yml"), "utf-8"),
		) as Record<string, any>) ?? {};
	const geoipRepos: GeoIPRepo[] = data.geoip ?? [];
	const defaultName: string = data.default?.geoip ?? "GeoIP AIO by daijro";
	return [geoipRepos, defaultName];
}

/**
 * Get GeoIP config by name from repos.yml. If omitted, uses the default.
 */
export function getGeoipConfigByName(name?: string | null): GeoIPRepo {
	const [repos, defaultName] = loadGeoipRepos();
	const targetName = name || defaultName;

	const validateRepo = (repo: GeoIPRepo): GeoIPRepo => {
		const raw = repo as Record<string, any>;
		if (!("urls" in raw)) {
			throw new Error(`GeoIP repo '${raw.name}' missing required urls`);
		}
		if (!("paths" in raw)) {
			throw new Error(`GeoIP repo '${raw.name}' missing required paths`);
		}
		return repo;
	};

	for (const repo of repos) {
		if ((repo.name ?? "").toLowerCase() === targetName.toLowerCase()) {
			return validateRepo(repo);
		}
	}

	if (name) {
		const available = repos.map((r) => `'${r.name ?? "Unknown"}'`);
		throw new Error(
			`GeoIP database '${name}' not found. Available: [${available.join(", ")}]`,
		);
	}

	if (repos.length) {
		return validateRepo(repos[0]);
	}
	throw new Error("No GeoIP repos configured in repos.yml");
}

/**
 * Warn that a GeoIP source is deprecated and name the default to use instead.
 */
export function warnIfDeprecated(config: GeoIPRepo): void {
	if (config.deprecated) {
		const [, defaultName] = loadGeoipRepos();
		warn(
			loadWarnings()
				.geoip_deprecated.replace("{name}", config.name)
				.replace("{default}", defaultName),
			"FutureWarning",
		);
	}
}

/**
 * Load the active GeoIP config from disk, falling back to the repos.yml default.
 *
 * A saved deprecated source that the user did not pick explicitly (every
 * cache written before the default changed) resolves to the default.
 */
export function loadGeoipConfig(): GeoIPRepo {
	if (fs.existsSync(GEOIP_CONFIG)) {
		const saved =
			(parseYaml(fs.readFileSync(GEOIP_CONFIG, "utf-8")) as Record<
				string,
				any
			>) ?? {};
		let config: GeoIPRepo;
		try {
			config = getGeoipConfigByName(saved.name);
		} catch {
			return saved as GeoIPRepo;
		}
		if (config.deprecated && !saved.explicit) {
			return getGeoipConfigByName(undefined);
		}
		return config;
	}
	return getGeoipConfigByName(undefined);
}

/**
 * Save the active GeoIP source name to disk. `explicit` records that the user
 * chose it, so a later default change does not move them off it.
 */
export function saveGeoipConfig(config: GeoIPRepo, explicit = false): void {
	fs.mkdirSync(GEOIP_DIR, { recursive: true });
	const saved: Record<string, unknown> = { name: config.name };
	if (explicit) {
		saved.explicit = true;
	}
	fs.writeFileSync(GEOIP_CONFIG, stringifyYaml(saved));
}

/**
 * Get the path to the mmdb file for the specified IP version.
 */
export function getMmdbPath(
	ipVersion: string = "ipv4",
	config?: GeoIPRepo,
): string {
	const cfg = config ?? loadGeoipConfig();
	const name = (cfg.name ?? "geolite2").toLowerCase();
	const urls = cfg.urls ?? {};
	if ("combined" in urls) {
		return path.join(MMDB_DIR, `${name}-combined.mmdb`);
	}
	return path.join(MMDB_DIR, `${name}-${ipVersion}.mmdb`);
}

/**
 * Checks that the mmdb reader is available.
 */
export function geoipAllowed(): void {
	if (!allowGeoip()) {
		throw new NotInstalledGeoIPExtra(
			"Please install the geoip extra to use this feature: npm install maxmind",
		);
	}
}

/**
 * Downloads the GeoIP database(s) to geoip/mmdb/. A named `source` becomes
 * the user's explicit choice unless `activate` is false.
 */
export async function downloadMmdb(
	source?: string,
	progressCallback?: (downloaded: number, total: number) => void,
	activate = true,
): Promise<void> {
	geoipAllowed();
	const { unzip, webdl } = await import("./pkgman.js");

	const config = source ? getGeoipConfigByName(source) : loadGeoipConfig();
	const urls = config.urls;
	const name = config.name.toLowerCase();

	fs.mkdirSync(MMDB_DIR, { recursive: true });

	const extract = config.extract ?? false;
	const isCombined = "combined" in urls;

	for (const [ipVer, rawList] of Object.entries(urls)) {
		const suffix = isCombined ? "" : ` (${ipVer})`;
		let dlDesc = `Downloading ${config.name}${suffix}`;
		let exDesc = `Extracting ${config.name}${suffix}`;
		const maxLen = Math.max(dlDesc.length, exDesc.length);
		dlDesc = dlDesc.padEnd(maxLen);
		exDesc = exDesc.padEnd(maxLen);

		const mmdbPath = path.join(MMDB_DIR, `${name}-${ipVer}.mmdb`);
		const urlList = typeof rawList === "string" ? [rawList] : rawList;

		let lastError: unknown;
		let done = false;
		for (const url of urlList) {
			const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-geoip-"));
			try {
				const buffer = await webdl(
					url,
					dlDesc,
					progressCallback === undefined,
					null,
					{ progressCallback },
				);
				if (extract) {
					unzip(buffer, tmpDir, exDesc, progressCallback === undefined);
					const found = findFirstMmdb(tmpDir);
					if (!found) {
						throw new Error("No .mmdb file found in archive");
					}
					fs.renameSync(found, mmdbPath);
				} else {
					fs.writeFileSync(mmdbPath, buffer);
				}
				// The mtime is when we last checked, which needsUpdate() throttles on
				const now = new Date();
				fs.utimesSync(mmdbPath, now, now);
				done = true;
				break;
			} catch (error) {
				lastError = error;
			} finally {
				fs.rmSync(tmpDir, { recursive: true, force: true });
			}
		}
		if (!done) {
			throw lastError ?? new Error(`Failed to download ${ipVer}`);
		}

		const age = await buildAgeDays(mmdbPath);
		if (age !== null && age > FROZEN_DAYS) {
			warn(
				loadWarnings()
					.geoip_frozen.replace("{name}", config.name)
					.replace("{days}", String(Math.trunc(age))),
				"RuntimeWarning",
			);
		}
	}

	removeDeprecatedDatabases(config);
	if (activate) {
		// A refresh of the active source keeps whether the user chose it
		saveGeoipConfig(config, Boolean(source) || chosenExplicitly(config));
	}
}

/** Whether the saved config names this source as the user's explicit choice. */
function chosenExplicitly(config: GeoIPRepo): boolean {
	if (!fs.existsSync(GEOIP_CONFIG)) return false;
	const saved =
		(parseYaml(fs.readFileSync(GEOIP_CONFIG, "utf-8")) as Record<
			string,
			any
		>) ?? {};
	return Boolean(saved.explicit) && saved.name === config.name;
}

/** Delete downloaded databases of deprecated sources other than `keep`. */
function removeDeprecatedDatabases(keep: GeoIPRepo): void {
	const [repos] = loadGeoipRepos();
	if (!fs.existsSync(MMDB_DIR)) return;
	for (const repo of repos) {
		if (!repo.deprecated || repo.name === keep.name) continue;
		const prefix = `${repo.name.toLowerCase()}-`;
		for (const file of fs.readdirSync(MMDB_DIR)) {
			if (file.startsWith(prefix) && file.endsWith(".mmdb")) {
				fs.rmSync(path.join(MMDB_DIR, file), { force: true });
			}
		}
	}
}

/** Days since the database's data was built, from its metadata. */
async function buildAgeDays(mmdbPath: string): Promise<number | null> {
	try {
		const reader = await geoipDeps.openDatabase(mmdbPath);
		try {
			const built = reader.metadata?.buildEpoch;
			return built ? (Date.now() - built.getTime()) / DAY_MS : null;
		} finally {
			reader.close?.();
		}
	} catch {
		return null;
	}
}

/** Path(tmpdir).rglob('*.mmdb')[0] */
function findFirstMmdb(dir: string): string | null {
	const entries = fs.readdirSync(dir, { withFileTypes: true, recursive: true });
	for (const entry of entries) {
		if (entry.isFile() && entry.name.endsWith(".mmdb")) {
			return path.join(entry.parentPath, entry.name);
		}
	}
	return null;
}

/**
 * Check if the GeoIP database needs an update: its data was built over
 * UPDATE_DAYS ago and it was last downloaded over RECHECK_DAYS ago.
 *
 * This reads the build date rather than the file's age, so a source that
 * keeps serving an old build is noticed.
 */
export async function needsUpdate(config?: GeoIPRepo): Promise<boolean> {
	const cfg = config ?? loadGeoipConfig();

	const ipv4Path = getMmdbPath("ipv4", cfg);
	if (!fs.existsSync(ipv4Path)) {
		return true;
	}
	const checkedDays = (Date.now() - fs.statSync(ipv4Path).mtimeMs) / DAY_MS;
	if (checkedDays < RECHECK_DAYS) {
		return false;
	}
	const buildDays = await buildAgeDays(ipv4Path);
	return buildDays === null || buildDays > UPDATE_DAYS;
}

/** float(x) for a value read out of the database. */
function pyFloat(value: any): number {
	if (value === null || value === undefined) {
		throw new TypeError(
			"float() argument must be a string or a real number, not 'NoneType'",
		);
	}
	const n = Number(value);
	if (Number.isNaN(n)) {
		throw new Error(`could not convert string to float: '${value}'`);
	}
	return n;
}

/**
 * Gets the geolocation for an IP address.
 */
export async function getGeolocation(
	ip: string,
	geoipDb?: string,
): Promise<Geolocation> {
	validateIP(ip);
	const ipVersion = ip.includes(":") ? "ipv6" : "ipv4";

	// A per-call geoipDb reads its own database without becoming the active one
	const config = geoipDb ? getGeoipConfigByName(geoipDb) : loadGeoipConfig();
	warnIfDeprecated(config);
	const mmdbPath = getMmdbPath(ipVersion, config);

	if (!fs.existsSync(mmdbPath) || (await needsUpdate(config))) {
		await geoipDeps.downloadMmdb(geoipDb);
	}
	const paths = config.paths;

	const reader = await geoipDeps.openDatabase(mmdbPath);
	try {
		const resp = reader.get(ip);
		if (!resp) {
			throw new UnknownIPLocation(`IP not found in database: ${ip}`);
		}

		const isoCode = findIn(resp, paths.iso_code);
		const longitude = findIn(resp, paths.longitude);
		const latitude = findIn(resp, paths.latitude);
		const timezone = findIn(resp, paths.timezone);

		const iso = String(isoCode ?? "None").toUpperCase();
		const locale = await SELECTOR.fromRegion(iso);

		return new Geolocation(
			locale,
			pyFloat(longitude),
			pyFloat(latitude),
			String(timezone ?? "None"),
		);
	} finally {
		reader.close?.();
	}
}
