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

export const GEOIP_DIR: string = path.join(INSTALL_DIR, "geoip");
export const MMDB_DIR: string = path.join(GEOIP_DIR, "mmdb");
export const GEOIP_CONFIG: string = path.join(GEOIP_DIR, "config.yml");

export interface GeoIPRepo {
	name: string;
	urls: Record<string, string | string[]>;
	paths: Record<string, string>;
	extract?: boolean;
	[key: string]: any;
}

/** A reader over an mmdb file: maxminddb.Reader's `get`. */
export interface MmdbReader {
	get(ip: string): any;
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
	downloadMmdb: (source?: string) => downloadMmdb(source),
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
	const defaultName: string = data.default?.geoip ?? "GeoLite2";
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
 * Load the active GeoIP config from disk, falling back to the repos.yml default.
 */
export function loadGeoipConfig(): GeoIPRepo {
	if (fs.existsSync(GEOIP_CONFIG)) {
		const saved =
			(parseYaml(fs.readFileSync(GEOIP_CONFIG, "utf-8")) as Record<
				string,
				any
			>) ?? {};
		try {
			return getGeoipConfigByName(saved.name);
		} catch {
			return saved as GeoIPRepo;
		}
	}
	return getGeoipConfigByName(undefined);
}

/**
 * Save the active GeoIP source name to disk.
 */
export function saveGeoipConfig(config: GeoIPRepo): void {
	fs.mkdirSync(GEOIP_DIR, { recursive: true });
	fs.writeFileSync(GEOIP_CONFIG, stringifyYaml({ name: config.name }));
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
 * Downloads the GeoIP database(s) to geoip/mmdb/.
 */
export async function downloadMmdb(
	source?: string,
	progressCallback?: (downloaded: number, total: number) => void,
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
	}

	saveGeoipConfig(config);
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
 * Check if the GeoIP database needs an update (older than 30 days).
 */
export function needsUpdate(config?: GeoIPRepo): boolean {
	const cfg = config ?? loadGeoipConfig();
	const updateDays = 30;

	const ipv4Path = getMmdbPath("ipv4", cfg);
	if (!fs.existsSync(ipv4Path)) {
		return true;
	}
	const age = Date.now() - fs.statSync(ipv4Path).mtimeMs;
	return age > updateDays * 24 * 60 * 60 * 1000;
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
	let mmdbPath = getMmdbPath(ipVersion);

	if (!fs.existsSync(mmdbPath) || needsUpdate()) {
		await geoipDeps.downloadMmdb();
		mmdbPath = getMmdbPath(ipVersion);
	}

	const config = geoipDb ? getGeoipConfigByName(geoipDb) : loadGeoipConfig();
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
