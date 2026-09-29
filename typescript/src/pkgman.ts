/**
 * Browser package management: version resolution, GitHub release discovery,
 * download/extract, and path lookup.
 *
 * TypeScript twin of pythonlib/camoufox/pkgman.py.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import * as fs from "node:fs";
import { createRequire } from "node:module";
import * as os from "node:os";
import * as path from "node:path";
import type { Writable } from "node:stream";
import AdmZip from "adm-zip";
import cliProgress, { type Options as BarOptions } from "cli-progress";
import prettyBytes from "pretty-bytes";
import { parse as parseYaml } from "yaml";
import { CONSTRAINTS, LIBRARY_VERSION } from "./__version__.js";
import {
	effectivePin,
	pinMatches,
	pinSpec,
	warnIfUnpaired,
} from "./browser-pin.js";
import {
	CamoufoxNotInstalled,
	CorruptedDownload,
	FileNotFoundError,
	MissingRelease,
	ProfileDirectoryError,
	UnsupportedArchitecture,
	UnsupportedOS,
	UnsupportedVersion,
} from "./exceptions.js";
// pkgman and multiversion are mutually dependent, exactly as the Python twin's
// function-local imports are. Every use below sits inside a function body, so
// the ESM cycle resolves before any binding is read.
import {
	COMPAT_FLAG,
	getActivePath,
	getDefaultChannel,
	installVersioned,
	loadConfig,
} from "./multiversion.js";
import {
	ARCH_MAP,
	INSTALL_DIR,
	LAUNCH_FILE,
	LOCAL_DATA,
	OS_ARCH_MATRIX,
	OS_MAP,
	OS_NAME,
	rprint,
} from "./paths.js";

// Platform constants and install paths live in paths.ts so that the
// pkgman <-> multiversion cycle never needs them mid-evaluation. Re-exported
// here so pkgman stays the single public entry point for them.
export {
	ARCH_MAP,
	INSTALL_DIR,
	LAUNCH_FILE,
	LOCAL_DATA,
	OS_ARCH_MATRIX,
	OS_MAP,
	OS_NAME,
	rprint,
	userCacheDir,
} from "./paths.js";

/** GITHUB_TOKEN, as the Python twin reads it: once, at import. */
const GITHUB_TOKEN: string | undefined = process.env.GITHUB_TOKEN;

/** Bearer auth for GitHub API calls only (never for asset downloads). */
function githubHeaders(url: string): Record<string, string> {
	return url.includes("api.github") && GITHUB_TOKEN
		? { Authorization: `Bearer ${GITHUB_TOKEN}` }
		: {};
}

/** requests' raise_for_status() message, so callers can match "404". */
function raiseForStatus(response: Response, url: string): void {
	if (response.ok) return;
	const kind = response.status < 500 ? "Client Error" : "Server Error";
	throw new Error(
		`${response.status} ${kind}: ${response.statusText} for url: ${url}`,
	);
}

/**
 * Ensure Firefox's Linux application directory exists before startup.
 *
 * Firefox probes ~/.camoufox even when Playwright supplies a temporary profile.
 * On a read-only HOME -- the normal shape for a container that bakes the bundle
 * in as root and runs as a non-root user -- a missing directory makes startup
 * stall with no diagnostic, surfacing as a launch timeout rather than as a
 * permissions error. An existing directory may itself still be read-only, which
 * is fine: Firefox only needs it to be there.
 */
export function ensureBrowserProfileDir(
	env?: Record<string, unknown>,
): string | undefined {
	if (OS_NAME !== "lin") return undefined;

	const environment = env ?? process.env;
	const configuredHome = environment.HOME;
	const home = configuredHome
		? expandUser(String(configuredHome))
		: os.homedir();
	const profileDir = path.join(home, ".camoufox");
	if (fs.existsSync(profileDir) && fs.statSync(profileDir).isDirectory()) {
		return profileDir;
	}

	try {
		fs.mkdirSync(profileDir, { recursive: true, mode: 0o700 });
	} catch (error) {
		throw new ProfileDirectoryError(
			`Camoufox requires '${profileDir}' to exist before launch, but it could ` +
				"not be created. For a read-only runtime, create this directory " +
				"before making HOME read-only.",
			{ cause: error },
		);
	}

	if (!fs.statSync(profileDir).isDirectory()) {
		throw new ProfileDirectoryError(
			`Camoufox requires '${profileDir}' to be a directory before launch.`,
		);
	}
	return profileDir;
}

/** os.path.expanduser for the forms a HOME value can take. */
function expandUser(p: string): string {
	if (p === "~") return os.homedir();
	if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2));
	return p;
}

/**
 * Parse a semver string into a comparable tuple.
 */
export function parseSemver(version: string): number[] {
	// A prerelease compares as its release: 0.5.8b1 (PEP 440) and 0.5.8-beta.1
	// (semver) are both 0.5.8, exactly as in the Python twin.
	const release = version
		.replace(/^[\^~]+/, "")
		.split(/(?<=\d)(?:[-+]|(?:a|b|rc|dev|\.dev|\.post)\d*)/)[0];
	const parts = release.split(".");
	// int() semantics: the whole part must be an integer ("1a" -> 0).
	const out = parts.map((part) =>
		/^\s*[+-]?\d+\s*$/.test(part) ? Number.parseInt(part, 10) : 0,
	);
	while (out.length < 3) out.push(0);
	return out;
}

function compareTuples(a: number[], b: number[]): number {
	const len = Math.max(a.length, b.length);
	for (let i = 0; i < len; i++) {
		const x = a[i] ?? 0;
		const y = b[i] ?? 0;
		if (x < y) return -1;
		if (x > y) return 1;
	}
	return 0;
}

/**
 * A comparable browser version string (up to 5 parts).
 */
export class Version {
	readonly build: string;
	readonly version?: string;
	readonly sortedRel: number[];

	constructor(build: string, version?: string) {
		this.build = build;
		this.version = version;
		// Mirrors the Python twin: digits stay numeric, a leading letter becomes
		// ord(c) - 1024 so "alpha" < "beta" < numeric builds sort sanely.
		const parts = build
			.split(".")
			.map((x) => (/^\d+$/.test(x) ? Number(x) : x.charCodeAt(0) - 1024));
		const padding = 5 - (build.split(".").length - 1);
		for (let i = 0; i < padding; i++) parts.push(0);
		this.sortedRel = parts;
	}

	get fullString(): string {
		return `${this.version}-${this.build}`;
	}

	/** Whether the build channel is alpha (like "alpha.26"). */
	get isAlpha(): boolean {
		return this.build.split(".")[0].toLowerCase() === "alpha";
	}

	compare(other: Version): number {
		return compareTuples(this.sortedRel, other.sortedRel);
	}

	equals(other: Version): boolean {
		return this.compare(other) === 0;
	}

	lessThan(other: Version): boolean {
		return this.compare(other) < 0;
	}

	greaterOrEqual(other: Version): boolean {
		return this.compare(other) >= 0;
	}

	isSupported(): boolean {
		return (
			this.compare(effectiveVersionMin()) >= 0 && this.compare(VERSION_MAX) < 0
		);
	}

	/**
	 * Read the version from version.json at the given path.
	 */
	static fromPath(dir: string = INSTALL_DIR): Version {
		const versionPath = path.join(dir, "version.json");
		if (!fs.existsSync(versionPath)) {
			throw new FileNotFoundError(
				`Version information not found at ${versionPath}. ` +
					"Please run `camoufox fetch` to install.",
			);
		}
		const data = JSON.parse(fs.readFileSync(versionPath, "utf-8"));
		// "release" and then "tag" win over "build", as the Python twin's pops do.
		const build =
			"release" in data ? data.release : "tag" in data ? data.tag : data.build;
		if (build === undefined) {
			throw new Error(`KeyError: 'build' (in ${versionPath})`);
		}
		return new Version(build, data.version ?? undefined);
	}

	static buildMinMax(): [Version, Version] {
		return [
			new Version(CONSTRAINTS.MIN_VERSION),
			new Version(CONSTRAINTS.MAX_VERSION),
		];
	}
}

export const [VERSION_MIN, VERSION_MAX] = Version.buildMinMax();

/**
 * Seams the Python tests reach with monkeypatch (VERSION_MIN,
 * _resolved_playwright_version, CamoufoxFetcher). Production code never
 * reassigns these.
 */
export const pkgmanDeps = {
	versionMin: (): Version => VERSION_MIN,
	resolvedPlaywrightVersion: (): number[] | null => resolvedPlaywrightVersion(),
	/** The fetcher the auto-install path runs `install()` on. */
	newFetcher: async (): Promise<{ install(): Promise<unknown> }> =>
		new CamoufoxFetcher().init(),
};

/**
 * The resolved playwright-core version string, or null when it cannot be read.
 * The Python twin asks importlib.metadata for `playwright`; the npm package
 * that plays that role here is playwright-core.
 */
function resolvedPlaywrightVersionRaw(): string | null {
	try {
		const require = createRequire(import.meta.url);
		const pkg = JSON.parse(
			fs.readFileSync(require.resolve("playwright-core/package.json"), "utf-8"),
		);
		return typeof pkg.version === "string" ? pkg.version : null;
	} catch {
		return null;
	}
}

/** The installed Playwright version, or null if it cannot be determined. */
export function resolvedPlaywrightVersion(): number[] | null {
	const raw = resolvedPlaywrightVersionRaw();
	return raw === null ? null : parseSemver(raw);
}

/** The installed Playwright version for messages ("the installed version"
 *  when it cannot be read). */
export function resolvedPlaywrightVersionStr(): string {
	return resolvedPlaywrightVersionRaw() ?? "the installed version";
}

/**
 * The lowest browser build this install can actually talk to.
 *
 * VERSION_MIN, raised by whatever the resolved Playwright requires. When the
 * Playwright version cannot be read we fall back to VERSION_MIN rather than
 * assuming the worst: a spurious forced re-download is worse than leaving a
 * working install alone, and package.json caps Playwright anyway.
 */
export function effectiveVersionMin(): Version {
	let floor = pkgmanDeps.versionMin();
	const playwrightVersion = pkgmanDeps.resolvedPlaywrightVersion();
	if (playwrightVersion === null) return floor;
	for (const [
		requiredPlaywright,
		build,
	] of CONSTRAINTS.PLAYWRIGHT_BROWSER_FLOORS) {
		if (
			compareTuples(playwrightVersion, [...requiredPlaywright]) >= 0 &&
			floor.lessThan(new Version(build))
		) {
			floor = new Version(build);
		}
	}
	return floor;
}

/** One `versions:` entry of a browser repo in repos.yml. */
export interface BrowserVersionConstraint {
	python_library?: { min?: string; max?: string };
	/** Absent means "assume every build is supported". */
	browser?: {
		stable?: { min?: string; max?: string };
		prerelease?: { min?: string; max?: string };
		min?: string;
		max?: string;
	} | null;
}

/** One `browsers:` entry of repos.yml. */
export interface BrowserRepoEntry {
	/** Primary repo first, then fallbacks: a comma-separated string or a list. */
	repo: string | string[];
	name: string;
	pattern?: string;
	versions?: BrowserVersionConstraint[];
}

/**
 * Load a bundled YAML data file (repos.yml, warnings.yml, ...).
 */
export function loadYaml(file: string): Record<string, any> {
	return (
		(parseYaml(fs.readFileSync(path.join(LOCAL_DATA, file), "utf-8")) as Record<
			string,
			any
		>) ?? {}
	);
}

/**
 * Find the browser build constraint for the current library version.
 */
function findVersionConstraints(
	versions: BrowserVersionConstraint[],
	libraryVersion: string,
): BrowserVersionConstraint["browser"] | undefined {
	const libParts = parseSemver(libraryVersion);
	let newest: BrowserVersionConstraint["browser"] | undefined;
	let newestMin: number[] | undefined;

	for (const entry of versions) {
		const pyLib = entry.python_library ?? {};
		const libMin = parseSemver(pyLib.min ?? "0");
		const libMax = parseSemver(pyLib.max ?? "999");
		if (
			compareTuples(libMin, libParts) <= 0 &&
			compareTuples(libParts, libMax) < 0
		) {
			return entry.browser;
		}
		if (newestMin === undefined || compareTuples(libMin, newestMin) > 0) {
			newestMin = libMin;
			newest = entry.browser;
		}
	}
	return newest;
}

/**
 * Get the min and max build bounds for a channel.
 */
function channelBounds(
	browser: BrowserVersionConstraint["browser"] | undefined,
	channel: "stable" | "prerelease",
): [string | undefined, string | undefined] {
	if (!browser) return [undefined, undefined];
	if ("stable" in browser || "prerelease" in browser) {
		const section = browser[channel] ?? {};
		return [section.min, section.max];
	}
	return [browser.min, browser.max];
}

/**
 * Configuration for a Camoufox repository.
 */
export class RepoConfig {
	repos: string[];
	name: string;
	pattern: string;
	stableMin?: string;
	stableMax?: string;
	prereleaseMin?: string;
	prereleaseMax?: string;

	constructor(init: {
		repos: string[];
		name: string;
		pattern: string;
		stableMin?: string;
		stableMax?: string;
		prereleaseMin?: string;
		prereleaseMax?: string;
	}) {
		this.repos = init.repos;
		this.name = init.name;
		this.pattern = init.pattern;
		this.stableMin = init.stableMin;
		this.stableMax = init.stableMax;
		this.prereleaseMin = init.prereleaseMin;
		this.prereleaseMax = init.prereleaseMax;
	}

	/** Primary GitHub repo. */
	get repo(): string {
		return this.repos[0];
	}

	static loadRepos(spoofLibraryVersion?: string): RepoConfig[] {
		const data = loadYaml("repos.yml");
		return ((data.browsers ?? []) as BrowserRepoEntry[]).map((r) =>
			RepoConfig.fromEntry(r, spoofLibraryVersion),
		);
	}

	static getDefaultName(): string {
		return loadYaml("repos.yml").default?.browser ?? "Official";
	}

	static fromEntry(
		entry: BrowserRepoEntry,
		spoofLibraryVersion?: string,
	): RepoConfig {
		if (!("pattern" in entry) || entry.pattern == null) {
			throw new Error(
				`Repo '${entry.name ?? "unknown"}' missing required pattern`,
			);
		}

		let browser: BrowserVersionConstraint["browser"] | undefined;
		if (entry.versions?.length) {
			browser = findVersionConstraints(
				entry.versions,
				spoofLibraryVersion || LIBRARY_VERSION,
			);
		}
		const [stableMin, stableMax] = channelBounds(browser, "stable");
		const [prereleaseMin, prereleaseMax] = channelBounds(browser, "prerelease");

		// Parse comma separated repos list (primary + fallbacks)
		const repos =
			typeof entry.repo === "string"
				? entry.repo.split(",").map((r) => r.trim())
				: entry.repo;

		return new RepoConfig({
			repos,
			name: entry.name,
			pattern: String(entry.pattern),
			stableMin,
			stableMax,
			prereleaseMin,
			prereleaseMax,
		});
	}

	static getDefault(): RepoConfig {
		const found = RepoConfig.findByName(RepoConfig.getDefaultName());
		return found ?? RepoConfig.loadRepos()[0];
	}

	static findByName(name: string): RepoConfig | undefined {
		const lower = name.toLowerCase();
		return RepoConfig.loadRepos().find((r) => r.name.toLowerCase() === lower);
	}

	getOsName(spoofOs?: string): string {
		if (spoofOs) return spoofOs;
		const osName = OS_MAP[process.platform];
		if (!osName) {
			throw new UnsupportedOS(`OS ${process.platform} is not supported`);
		}
		return osName;
	}

	getArch(spoofArch?: string): string {
		if (spoofArch) return spoofArch;
		const platArch = os.arch().toLowerCase();
		const arch = ARCH_MAP[platArch];
		if (!arch) {
			throw new UnsupportedArchitecture(
				`Architecture ${platArch} is not supported`,
			);
		}
		return arch;
	}

	/**
	 * Build the asset regex from the config pattern string.
	 */
	buildPattern(spoofOs?: string, spoofArch?: string): RegExp {
		const replacements: Record<string, string> = {
			name: "(?<name>\\w+)",
			version: "(?<version>[^-]+)",
			build: "(?<build>[^-]+)",
			os: escapeRegExp(this.getOsName(spoofOs)),
			arch: escapeRegExp(this.getArch(spoofArch)),
		};
		const pattern = this.pattern.replace(/\./g, "\\.");
		const regex = pattern.replace(
			/\{(\w+)\}/g,
			(match, key) => replacements[key] ?? match,
		);
		return new RegExp(`^${regex}`);
	}

	/**
	 * Check if a build is within the supported range for its channel.
	 */
	isVersionSupported(version: Version, isPrerelease: boolean = false): boolean {
		const buildMin = isPrerelease ? this.prereleaseMin : this.stableMin;
		const buildMax = isPrerelease ? this.prereleaseMax : this.stableMax;
		if (buildMin == null || buildMax == null) {
			return true;
		}
		return (
			new Version(buildMin).compare(version) <= 0 &&
			version.compare(new Version(buildMax)) <= 0
		);
	}
}

/** Python's str ordering (code points), not localeCompare's collation. */
export function cmpStr(a: string, b: string): number {
	return a < b ? -1 : a > b ? 1 : 0;
}

function escapeRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export interface GitHubAsset {
	name: string;
	browser_download_url: string;
	id?: number;
	size?: number;
	updated_at?: string;
	created_at?: string;
	digest?: string;
}

export interface GitHubRelease {
	prerelease?: boolean;
	assets: GitHubAsset[];
}

/**
 * Manages fetching GitHub releases with fallback repos.
 */
export class GitHubDownloader {
	githubRepos: string[];
	githubRepo: string;
	isPrerelease = false;

	constructor(githubRepos: string | string[]) {
		this.githubRepos =
			typeof githubRepos === "string" ? [githubRepos] : githubRepos;
		this.githubRepo = this.githubRepos[0];
	}

	/** Return truthy data if this is the desired asset, else null. */
	checkAsset(asset: GitHubAsset, _release?: GitHubRelease): any {
		return asset.browser_download_url;
	}

	missingAssetError(): never {
		throw new MissingRelease(
			`Could not find a release asset in ${this.githubRepo}.`,
		);
	}

	protected async getReleases(githubRepo: string): Promise<GitHubRelease[]> {
		const apiUrl = `https://api.github.com/repos/${githubRepo}/releases`;
		const response = await fetch(apiUrl, {
			headers: githubHeaders(apiUrl),
			signal: AbortSignal.timeout(20_000),
		});
		raiseForStatus(response, apiUrl);
		return (await response.json()) as GitHubRelease[];
	}

	/**
	 * Fetch the first matching release asset, trying fallback repos on failure.
	 */
	async getAsset(): Promise<any> {
		let lastError: unknown;
		for (const repo of this.githubRepos) {
			try {
				const releases = await this.getReleases(repo);
				for (const release of releases) {
					for (const asset of release.assets ?? []) {
						const data = this.checkAsset(asset, release);
						if (data) {
							this.githubRepo = repo;
							this.isPrerelease = release.prerelease ?? false;
							return data;
						}
					}
				}
			} catch (error) {
				lastError = error;
			}
		}

		if (lastError) throw lastError;
		this.missingAssetError();
	}
}

/**
 * Information about an available Camoufox version on GitHub.
 */
export class AvailableVersion {
	version: Version;
	url: string;
	isPrerelease: boolean;
	assetId?: number;
	assetSize?: number;
	assetUpdatedAt?: string;
	sha256?: string;
	assetCreatedAt?: string;

	constructor(init: {
		version: Version;
		url: string;
		isPrerelease: boolean;
		assetId?: number;
		assetSize?: number;
		assetUpdatedAt?: string;
		sha256?: string;
		assetCreatedAt?: string;
	}) {
		Object.assign(this, init);
		this.version = init.version;
		this.url = init.url;
		this.isPrerelease = init.isPrerelease;
	}

	/** First 8 hex chars of the sha256, or empty when unknown. */
	get sha8(): string {
		return (this.sha256 ?? "").slice(0, 8);
	}

	get display(): string {
		const pre = this.isPrerelease ? " (prerelease)" : "";
		return `v${this.version.fullString}${pre}`;
	}

	toMetadata(): Record<string, any> {
		return {
			version: this.version.version ?? null,
			build: this.version.build,
			prerelease: this.isPrerelease,
			asset_id: this.assetId ?? null,
			asset_size: this.assetSize ?? null,
			asset_updated_at: this.assetUpdatedAt ?? null,
			sha256: this.sha256 ?? null,
			created_at: this.assetCreatedAt ?? null,
		};
	}
}

/**
 * Handles fetching and installing Camoufox.
 */
export class CamoufoxFetcher extends GitHubDownloader {
	repoConfig: RepoConfig;
	arch: string;
	pattern: RegExp;
	installedSha256?: string;
	installedCreatedAt?: string;
	_versionObj?: Version;
	_selectedVersion?: AvailableVersion;
	_url?: string;

	constructor(repoConfig?: RepoConfig, selectedVersion?: AvailableVersion) {
		const config = repoConfig ?? RepoConfig.getDefault();
		super(config.repos);
		this.repoConfig = config;
		this.arch = this.getPlatformArch();
		this.pattern = this.repoConfig.buildPattern();

		if (selectedVersion) {
			this._selectedVersion = selectedVersion;
			this._versionObj = selectedVersion.version;
			this._url = selectedVersion.url;
			this.isPrerelease = selectedVersion.isPrerelease;
			this.installedSha256 = selectedVersion.sha256;
			this.installedCreatedAt = selectedVersion.assetCreatedAt;
		}
	}

	/**
	 * The Python constructor calls fetch_latest() inline; downloads are async in
	 * JS, so callers do `await new CamoufoxFetcher().init()` instead.
	 */
	async init(): Promise<this> {
		if (!this._versionObj) {
			await this.fetchLatest();
		}
		return this;
	}

	/** First 8 hex chars of the installed asset sha, or empty. */
	get installedSha8(): string {
		return (this.installedSha256 ?? "").slice(0, 8);
	}

	/**
	 * Match a release asset against version constraints, OS, and arch.
	 */
	checkAsset(
		asset: GitHubAsset,
		release?: GitHubRelease,
	): [Version, string] | null {
		const match = this.pattern.exec(asset.name);
		if (!match?.groups) return null;

		const version = new Version(match.groups.build, match.groups.version);
		// A released library installs exactly the browser it was released with
		// (browser-pin.ts), unless the user explicitly chose something else.
		const pin = effectivePin(loadConfig());
		if (
			pin &&
			!pinMatches(
				pin,
				this.repoConfig.name,
				match.groups.version,
				match.groups.build,
			)
		) {
			return null;
		}
		const isPrerelease = Boolean(release?.prerelease) || version.isAlpha;
		if (!pin && !this.repoConfig.isVersionSupported(version, isPrerelease)) {
			return null;
		}

		const digest = asset.digest ?? "";
		if (digest.startsWith("sha256:")) {
			this.installedSha256 = digest.slice("sha256:".length);
		}
		this.installedCreatedAt = asset.created_at;

		return [version, asset.browser_download_url];
	}

	missingAssetError(): never {
		throw new MissingRelease(
			`No matching release found for ${OS_NAME} ${this.arch} in the ` +
				"supported range. Please update the Python library.",
		);
	}

	getPlatformArch(): string {
		const arch = (this.repoConfig ?? RepoConfig.getDefault()).getArch();
		if (!OS_ARCH_MATRIX[OS_NAME].includes(arch)) {
			throw new UnsupportedArchitecture(
				`Architecture ${arch} is not supported for ${OS_NAME}`,
			);
		}
		return arch;
	}

	/**
	 * Fetch the latest camoufox release for the current platform.
	 */
	async fetchLatest(): Promise<void> {
		const [versionObj, url] = await this.getAsset();
		this._versionObj = versionObj;
		this._url = url;
	}

	static async downloadFile(file: Writable, url: string): Promise<void> {
		rprint(`Downloading package: ${url}`);
		await webdl(url, undefined, true, file);
	}

	/**
	 * Download and install camoufox to a versioned subdirectory.
	 */
	async install(replace: boolean = false): Promise<boolean> {
		const installed = await installVersioned(this, replace);
		ensureBrowserProfileDir();
		return installed;
	}

	get url(): string {
		if (!this._url) {
			throw new Error("Url is not available. Make sure to run init() first.");
		}
		return this._url;
	}

	get version(): string {
		if (!this._versionObj?.version) {
			throw new Error(
				"Version is not available. Make sure to run init() first.",
			);
		}
		return this._versionObj.version;
	}

	get build(): string {
		if (!this._versionObj) {
			throw new Error(
				"Build information is not available. Make sure to run init() first.",
			);
		}
		return this._versionObj.build;
	}

	get verstr(): string {
		if (!this._versionObj) {
			throw new Error(
				"Version is not available. Make sure to run init() first.",
			);
		}
		return this._versionObj.fullString;
	}
}

/**
 * Fetch all supported versions from GitHub for the current platform.
 */
export async function listAvailableVersions(
	repoConfig?: RepoConfig,
	includePrerelease: boolean = true,
	spoofOs?: string,
	spoofArch?: string,
): Promise<AvailableVersion[]> {
	const config = repoConfig ?? RepoConfig.getDefault();
	const pattern = config.buildPattern(spoofOs, spoofArch);

	const osName = spoofOs ?? OS_NAME;
	const arch = config.getArch(spoofArch);
	if (!(OS_ARCH_MATRIX[osName] ?? []).includes(arch)) {
		throw new UnsupportedArchitecture(
			`Architecture ${arch} is not supported for ${osName}`,
		);
	}

	let releases: GitHubRelease[] = [];
	let lastError: unknown;
	for (const repo of config.repos) {
		try {
			const apiUrl = `https://api.github.com/repos/${repo}/releases`;
			const resp = await fetch(apiUrl, {
				headers: githubHeaders(apiUrl),
				signal: AbortSignal.timeout(20_000),
			});
			raiseForStatus(resp, apiUrl);
			releases = (await resp.json()) as GitHubRelease[];
			break;
		} catch (error) {
			lastError = error;
		}
	}
	if (!releases.length && lastError) throw lastError;

	const versions: AvailableVersion[] = [];

	for (const release of releases) {
		const isPrerelease = release.prerelease ?? false;
		if (isPrerelease && !includePrerelease) continue;

		for (const asset of release.assets ?? []) {
			const match = pattern.exec(asset.name);
			if (!match?.groups) continue;

			const version = new Version(match.groups.build, match.groups.version);
			const assetPrerelease = isPrerelease || version.isAlpha;
			if (assetPrerelease && !includePrerelease) continue;
			if (!config.isVersionSupported(version, assetPrerelease)) continue;

			const digest = asset.digest ?? "";
			const sha256 = digest.startsWith("sha256:")
				? digest.slice("sha256:".length)
				: undefined;

			versions.push(
				new AvailableVersion({
					version,
					url: asset.browser_download_url,
					isPrerelease: assetPrerelease,
					assetId: asset.id,
					assetSize: asset.size,
					assetUpdatedAt: asset.updated_at,
					sha256,
					assetCreatedAt: asset.created_at,
				}),
			);
		}
	}

	versions.sort((a, b) => {
		const byVersion = b.version.compare(a.version);
		if (byVersion !== 0) return byVersion;
		return cmpStr(b.assetCreatedAt ?? "", a.assetCreatedAt ?? "");
	});
	return versions;
}

/**
 * Get the full version string of the active install.
 */
export function installedVerStr(fromDir?: string): string {
	// An explicit directory (the folder holding a sandbox/alt-version
	// executable_path) reads that build's version.json instead of the active
	// install's. Mac-bundle aware: an executable inside
	// Camoufox.app/Contents/MacOS/ belongs to an install whose version.json sits
	// three levels up -- unless a deployment stamped one beside the binary.
	if (fromDir) {
		let dir = fromDir;
		if (
			path.basename(dir) === "MacOS" &&
			!fs.existsSync(path.join(dir, "version.json"))
		) {
			dir = path.dirname(path.dirname(path.dirname(dir)));
		}
		return Version.fromPath(dir).fullString;
	}

	const active = getActivePath();
	if (active === null) throw notInstalledError();
	const version = Version.fromPath(active);
	if (path.basename(path.dirname(path.dirname(active))) === "browsers") {
		warnIfUnpaired(
			path.basename(path.dirname(active)),
			version.version ?? "",
			version.build,
		);
	}
	return version.fullString;
}

/**
 * Whether INSTALL_DIR's root holds a supported build.
 *
 * Only the pre-multiversion flat layout wrote version.json at the root; the
 * versioned layout keeps it under browsers/<repo>/<version>/. A missing root
 * version.json means "no legacy install here", so the caller should fall
 * through to a fetch rather than raise. The alpha.1 floor masked this: no
 * install was ever unsupported, so this branch was never reached.
 */
export function rootInstallSupported(): boolean {
	try {
		return Version.fromPath().isSupported();
	} catch (error) {
		if (error instanceof FileNotFoundError) return false;
		throw error;
	}
}

/** What is missing -- the paired build, a pin, or a channel -- and how to get it. */
function notInstalledError(): CamoufoxNotInstalled {
	const config = loadConfig();
	const pin = effectivePin(config);
	const pinned = config.pinned;
	const channel = config.channel || getDefaultChannel();
	const missing = pin
		? `${pin.repoName} ${pinSpec(pin)}, the browser this camoufox release pairs with,`
		: pinned
			? `${channel}/${pinned}`
			: channel;
	return new CamoufoxNotInstalled(
		`${missing} is not installed. Please run \`camoufox fetch\` to install.`,
	);
}

/**
 * The part of the Python twin's camoufox_path() that runs before it would
 * download: returns the install to use, or null when a fetch is needed (only
 * possible with `downloadIfMissing`; otherwise the Python errors are raised).
 */
function resolveInstalledPath(downloadIfMissing: boolean): string | null {
	// Clean up incompatible old data directory
	if (
		fs.existsSync(INSTALL_DIR) &&
		fs.readdirSync(INSTALL_DIR).length > 0 &&
		!fs.existsSync(COMPAT_FLAG)
	) {
		rprint("Cleaning old data...", "yellow");
		fs.rmSync(INSTALL_DIR, { recursive: true, force: true });
	}

	const active = getActivePath();
	if (active && Version.fromPath(active).isSupported()) {
		return active;
	}

	if (!fs.existsSync(INSTALL_DIR) || fs.readdirSync(INSTALL_DIR).length === 0) {
		if (!downloadIfMissing) throw notInstalledError();
	} else if (rootInstallSupported()) {
		return INSTALL_DIR;
	} else if (!downloadIfMissing) {
		// Other builds are installed, but not the one this release pairs with.
		if (effectivePin(loadConfig())) throw notInstalledError();
		throw new UnsupportedVersion("Camoufox executable is outdated.");
	}
	return null;
}

/**
 * Full path to the active camoufox folder.
 *
 * This is the Python twin's camoufox_path(download_if_missing=False): it is
 * called from synchronous path helpers, and a download is asynchronous in JS.
 * `ensureCamoufoxInstalled()` is the download_if_missing=True half;
 * `launchOptions()` awaits it before any path lookup, so first-run
 * auto-download behaviour is preserved.
 */
export function camoufoxPath(): string {
	return resolveInstalledPath(false) as string;
}

/**
 * Resolve the active browser, downloading it first when nothing usable is
 * installed. The async counterpart to the Python twin's camoufox_path().
 */
export async function ensureCamoufoxInstalled(): Promise<string> {
	const found = resolveInstalledPath(true);
	if (found !== null) return found;

	const fetcher = await pkgmanDeps.newFetcher();
	await fetcher.install();

	// Re-check rather than recurse.
	//
	// If the newest published build is still below the floor -- a library
	// published ahead of its browser release, or a repos source that does not
	// carry it -- install() is a no-op ("already installed") and recursing here
	// spun ~1000 fetch attempts into a stack overflow, having hammered the
	// GitHub API into a rate limit on the way. Say what is actually wrong.
	const active = getActivePath();
	if (active && Version.fromPath(active).isSupported()) {
		return active;
	}
	if (fs.existsSync(INSTALL_DIR) && rootInstallSupported()) {
		return INSTALL_DIR;
	}
	throw new UnsupportedVersion(
		"No available Camoufox build satisfies this library's minimum " +
			`(${CONSTRAINTS.MIN_VERSION}). The matching browser release may not be ` +
			"published yet; wait for it, or install an older camoufox release.",
	);
}

/**
 * Get the path to a file in the camoufox directory.
 *
 * `baseDir` (the directory of an explicit/sandbox executable_path) resolves
 * resources relative to that build instead of the active install, so a sandbox
 * binary doesn't fall back to the cache dir.
 */
export function getPath(file: string, baseDir?: string): string {
	if (baseDir) {
		// Mac-bundle aware: an executable in Camoufox.app/Contents/MacOS/ keeps
		// its resources under ../Resources/.
		if (path.basename(baseDir) === "MacOS") {
			return path.join(baseDir, "..", "Resources", file);
		}
		return path.join(baseDir, file);
	}
	if (OS_NAME === "mac") {
		return path.resolve(
			camoufoxPath(),
			"Camoufox.app",
			"Contents",
			"Resources",
			file,
		);
	}
	return path.join(camoufoxPath(), file);
}

/**
 * Get the path to the camoufox executable.
 */
export function launchPath(browserPath?: string): string {
	let execPath: string;
	if (browserPath) {
		execPath =
			OS_NAME === "mac"
				? path.resolve(
						browserPath,
						"Camoufox.app",
						"Contents",
						"Resources",
						LAUNCH_FILE[OS_NAME],
					)
				: path.join(browserPath, LAUNCH_FILE[OS_NAME]);
	} else {
		execPath = getPath(LAUNCH_FILE[OS_NAME]);
	}

	if (!fs.existsSync(execPath)) {
		throw new CamoufoxNotInstalled(
			`Camoufox is not installed at ${browserPath ?? camoufoxPath()}. ` +
				"Please run `camoufox fetch` to install.",
		);
	}
	return execPath;
}

const formatBytes = (v: number, _: BarOptions, type: string) =>
	type === "total" || type === "value" ? prettyBytes(v) : String(v);

export type ProgressCallback = (downloaded: number, total: number) => void;

/**
 * Download a file from the given URL. Streams into `buffer` when one is given,
 * otherwise accumulates and returns the bytes.
 *
 * One attempt, like the Python twin's requests.get(): an HTTP error raises
 * requests' "<status> Client Error: ... for url: ..." message.
 */
export async function webdl(
	url: string,
	desc?: string,
	bar: boolean = true,
	buffer: Writable | null = null,
	{ progressCallback }: { progressCallback?: ProgressCallback } = {},
): Promise<Buffer> {
	const response = await fetch(url, { headers: githubHeaders(url) });
	raiseForStatus(response, url);

	const totalSize = Number.parseInt(
		response.headers.get("content-length") || "0",
		10,
	);
	let progressBar: cliProgress.SingleBar | null = null;
	if (!progressCallback && bar) {
		progressBar = new cliProgress.SingleBar(
			{
				format: `${desc || "Downloading"} [{bar}] {percentage}% | ETA: {eta_formatted} | {value}/{total}`,
				formatValue: formatBytes,
				noTTYOutput: true,
			},
			cliProgress.Presets.shades_classic,
		);
		progressBar.start(totalSize, 0);
	}

	const chunks: Uint8Array[] = [];
	let downloaded = 0;
	let lastUpdate = 0;
	try {
		if (!response.body) {
			throw new Error(`Response from ${url} had no body`);
		}
		for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
			if (buffer) {
				// A stream that already failed (disk full) never drains: surface
				// its error instead of waiting on it. When it is merely slow,
				// wait for it, or the whole archive ends up queued in memory.
				if (buffer.errored) throw buffer.errored;
				if (!buffer.write(chunk)) await once(buffer, "drain");
			} else {
				chunks.push(chunk);
			}
			downloaded += chunk.length;
			if (progressCallback) {
				if (downloaded - lastUpdate >= 65536 || downloaded === totalSize) {
					progressCallback(downloaded, totalSize);
					lastUpdate = downloaded;
				}
			} else if (progressBar) {
				progressBar.increment(chunk.length);
			} else if (totalSize) {
				const pct = (downloaded / totalSize) * 100;
				process.stdout.write(`\r${desc}: ${pct.toFixed(0)}%`);
			}
		}
	} finally {
		progressBar?.stop();
	}
	if (!progressCallback && !bar) {
		process.stdout.write(desc ? `\r${desc}: Complete\n` : "\n");
	}

	return Buffer.concat(chunks);
}

/**
 * Check a downloaded file against its expected sha256 digest.
 *
 * Takes the downloaded bytes or the path of the file they were written to.
 * Raises CorruptedDownload on mismatch. Skips (with a warning) when no digest
 * is known, so installs from sources that publish no digest still work.
 */
export function verifySha256(
	buffer: Buffer | Uint8Array | string,
	expected: string | null | undefined,
	desc: string = "asset",
): void {
	if (!expected) {
		rprint(
			`Warning: no sha256 published for ${desc}; skipping verification.`,
			"yellow",
		);
		return;
	}

	const digest = createHash("sha256");
	if (typeof buffer === "string") {
		const fd = fs.openSync(buffer, "r");
		try {
			const block = Buffer.alloc(1024 * 1024);
			let read = fs.readSync(fd, block, 0, block.length, null);
			while (read > 0) {
				digest.update(block.subarray(0, read));
				read = fs.readSync(fd, block, 0, block.length, null);
			}
		} finally {
			fs.closeSync(fd);
		}
	} else {
		digest.update(buffer);
	}

	const actual = digest.digest("hex");
	if (actual !== expected.toLowerCase()) {
		throw new CorruptedDownload(
			`Checksum mismatch for ${desc}.\n` +
				`  expected sha256: ${expected.toLowerCase()}\n` +
				`  actual   sha256: ${actual}\n` +
				"The download was corrupted or tampered with. Installation aborted.",
		);
	}
}

/**
 * Extract a zip file to the given path.
 */
export function unzip(
	zipFile: Buffer | string,
	extractPath: string,
	desc?: string,
	bar: boolean = true,
): void {
	const zip = new AdmZip(zipFile);
	const entries = zip.getEntries();

	if (bar) {
		rprint(desc || "Extracting");
		for (const entry of entries) {
			zip.extractEntryTo(entry, extractPath, true, true);
		}
		return;
	}

	entries.forEach((entry, i) => {
		zip.extractEntryTo(entry, extractPath, true, true);
		if (desc) {
			const pct = ((i + 1) / entries.length) * 100;
			process.stdout.write(`\r${desc}: ${pct.toFixed(0)}%`);
		}
	});
	if (desc) process.stdout.write(`\r${desc}: Complete\n`);
}

/**
 * chmod -R 755 on POSIX so the freshly-extracted binaries are executable.
 * (The zip does not carry usable permission bits on every platform.)
 */
export function makeExecutable(dir: string): void {
	if (OS_NAME === "win") return;
	try {
		execFileSync("chmod", ["-R", "755", dir]);
	} catch (error) {
		rprint(`Warning: could not chmod ${dir}: ${error}`, "yellow");
	}
}

/**
 * Format an asset timestamp as "Mon D", or "Mon D, YYYY" when the year differs.
 */
export function formatAssetDate(iso?: string, now?: Date): string {
	if (!iso) return "";
	const dt = new Date(iso);
	if (Number.isNaN(dt.getTime())) return "";
	const currentYear = (now ?? new Date()).getFullYear();
	const month = dt.toLocaleString("en-US", { month: "short" });
	if (dt.getFullYear() === currentYear) {
		return `${month} ${dt.getDate()}`;
	}
	return `${month} ${dt.getDate()}, ${dt.getFullYear()}`;
}
