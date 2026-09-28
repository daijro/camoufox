/**
 * Manager for handling multiple Camoufox versions side by side.
 *
 * TypeScript twin of pythonlib/camoufox/multiversion.py.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { finished } from "node:stream/promises";
import { effectivePin, pinMatches } from "./browser-pin.js";
import { INSTALL_DIR, OS_NAME, rprint } from "./paths.js";
// pkgman and multiversion are mutually dependent, exactly as the Python twin's
// function-local imports are. Every use of these sits inside a function body,
// so the ESM cycle resolves before any binding is read.
import {
	type AvailableVersion,
	type CamoufoxFetcher,
	cmpStr,
	formatAssetDate,
	makeExecutable,
	RepoConfig,
	unzip,
	Version,
	verifySha256,
} from "./pkgman.js";

export const BROWSERS_DIR: string = path.join(INSTALL_DIR, "browsers");
export const CONFIG_FILE: string = path.join(INSTALL_DIR, "config.json");
export const REPO_CACHE_FILE: string = path.join(
	INSTALL_DIR,
	"repo_cache.json",
);
export const COMPAT_FLAG: string = path.join(INSTALL_DIR, ".0.5_FLAG");

export interface CamoufoxConfig {
	active_version?: string | null;
	channel?: string;
	pinned?: string;
	pinned_sha?: string;
	geoip?: string;
	[key: string]: unknown;
}

/**
 * Load user config from disk, or return an empty object.
 */
export function loadConfig(): CamoufoxConfig {
	if (fs.existsSync(CONFIG_FILE)) {
		try {
			return JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8"));
		} catch {
			// Corrupt config: treat as absent, exactly as the Python twin does.
		}
	}
	return {};
}

/**
 * Get the default repo's stable channel string (like official/stable).
 */
export function getDefaultChannel(): string {
	return `${RepoConfig.getDefaultName().toLowerCase()}/stable`;
}

/**
 * Save user config to disk.
 */
export function saveConfig(config: CamoufoxConfig): void {
	fs.mkdirSync(INSTALL_DIR, { recursive: true });
	fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
}

export interface CachedVersion {
	version: string;
	build: string;
	url: string;
	is_prerelease?: boolean;
	asset_id?: number;
	asset_size?: number;
	asset_updated_at?: string;
	sha256?: string;
	created_at?: string;
}

export interface RepoCache {
	repos?: Array<{ name: string; versions?: CachedVersion[] }>;
	[key: string]: unknown;
}

/**
 * Load cached repo data from disk.
 */
export function loadRepoCache(): RepoCache {
	if (fs.existsSync(REPO_CACHE_FILE)) {
		try {
			return JSON.parse(fs.readFileSync(REPO_CACHE_FILE, "utf-8"));
		} catch {
			// Corrupt cache: treat as absent.
		}
	}
	return {};
}

/**
 * Save repo cache to disk.
 */
export function saveRepoCache(cache: RepoCache): void {
	fs.mkdirSync(INSTALL_DIR, { recursive: true });
	fs.writeFileSync(REPO_CACHE_FILE, JSON.stringify(cache, null, 2));
}

/**
 * Keep one cache entry per version-build, the newest by created_at.
 */
export function latestPerBuild(versions: CachedVersion[]): CachedVersion[] {
	const best = new Map<string, CachedVersion>();
	for (const v of versions) {
		const key = `${v.version}-${v.build}`;
		const cur = best.get(key);
		if (!cur || (v.created_at ?? "") > (cur.created_at ?? "")) {
			best.set(key, v);
		}
	}
	return [...best.values()].sort((a, b) => {
		const byVersion = cmpStr(b.version, a.version);
		if (byVersion !== 0) return byVersion;
		return cmpStr(b.created_at ?? "", a.created_at ?? "");
	});
}

/**
 * Get the display name for a repo from the repo config, lowercased.
 */
export function getRepoName(githubRepo: string): string {
	for (const repo of RepoConfig.loadRepos()) {
		if (repo.repos.includes(githubRepo)) {
			return repo.name.toLowerCase();
		}
	}
	return githubRepo.split("/")[0].toLowerCase();
}

/**
 * Information about an installed Camoufox version.
 */
export class InstalledVersion {
	repoName: string;
	version: Version;
	path: string;
	isActive: boolean;
	isPrerelease: boolean;
	assetId?: number;
	assetSize?: number;
	assetUpdatedAt?: string;
	sha256?: string;
	createdAt?: string;

	constructor(init: {
		repoName: string;
		version: Version;
		path: string;
		isActive?: boolean;
		isPrerelease?: boolean;
		assetId?: number;
		assetSize?: number;
		assetUpdatedAt?: string;
		sha256?: string;
		createdAt?: string;
	}) {
		this.repoName = init.repoName;
		this.version = init.version;
		this.path = init.path;
		this.isActive = init.isActive ?? false;
		this.isPrerelease = init.isPrerelease ?? false;
		this.assetId = init.assetId;
		this.assetSize = init.assetSize;
		this.assetUpdatedAt = init.assetUpdatedAt;
		this.sha256 = init.sha256;
		this.createdAt = init.createdAt;
	}

	/** Folder name, e.g. 150.0.2-beta.25-8020db3b. */
	get folderName(): string {
		return path.basename(this.path);
	}

	/** Path relative to INSTALL_DIR, e.g. browsers/official/150.0.2-beta.25. */
	get relativePath(): string {
		return `browsers/${this.repoName}/${this.folderName}`;
	}

	/** Channel display string (like official/stable/134.0.2-beta.20). */
	get channelPath(): string {
		const ctype = this.isPrerelease ? "prerelease" : "stable";
		return `${this.repoName}/${ctype}/${this.version.fullString}`;
	}

	/**
	 * Compare with an available version and return change indicators.
	 */
	getChanges(available: AvailableVersion): string[] {
		const changes: string[] = [];
		if (this.isPrerelease && !available.isPrerelease) {
			changes.push("prerelease -> stable");
		} else if (!this.isPrerelease && available.isPrerelease) {
			changes.push("stable -> prerelease");
		}

		if (this.assetUpdatedAt && available.assetUpdatedAt) {
			if (this.assetUpdatedAt !== available.assetUpdatedAt) {
				changes.push("asset updated");
			}
		} else if (this.assetSize && available.assetSize) {
			if (this.assetSize !== available.assetSize) {
				changes.push("asset updated");
			}
		}

		return changes;
	}
}

/**
 * Install folder name with an optional sha8 suffix.
 */
export function versionFolderName(
	version: string,
	build: string,
	sha8: string = "",
): string {
	const base = `${version}-${build}`;
	return sha8 ? `${base}-${sha8}` : base;
}

/**
 * Get the installed folder for a catalog item. Falls back to version-build/
 * (without the sha8) for backwards compatibility.
 */
function matchInstall(
	full: string,
	sha256: string | undefined,
	byFolder: Map<string, InstalledVersion>,
	count: number,
): InstalledVersion | null {
	const sha8 = (sha256 ?? "").slice(0, 8);
	if (sha8) {
		const exact = byFolder.get(`${full}-${sha8}`);
		if (exact) return exact;
	}
	const legacy = byFolder.get(full);
	if (!legacy) return null;
	if (legacy.sha256) {
		return legacy.sha256 === sha256 ? legacy : null;
	}
	return count <= 1 ? legacy : null;
}

/**
 * Match each catalog item to an install folder.
 * Returns the matches and any orphaned leftovers.
 */
export function classifyInstalls(
	versions: AvailableVersion[],
	installed: InstalledVersion[],
): [Array<InstalledVersion | null>, Array<[InstalledVersion, string]>] {
	const counts = new Map<string, number>();
	for (const v of versions) {
		const key = v.version.fullString;
		counts.set(key, (counts.get(key) ?? 0) + 1);
	}
	const byFolder = new Map(installed.map((iv) => [iv.folderName, iv]));

	const rowInst: Array<InstalledVersion | null> = [];
	const matched = new Set<string>();
	for (const v of versions) {
		const full = v.version.fullString;
		const inst = matchInstall(full, v.sha256, byFolder, counts.get(full) ?? 0);
		rowInst.push(inst);
		if (inst) matched.add(inst.folderName);
	}

	const extras: Array<[InstalledVersion, string]> = [];
	for (const iv of installed) {
		if (matched.has(iv.folderName)) continue;
		const inCatalog = (counts.get(iv.version.fullString) ?? 0) > 0;
		const note = inCatalog && !iv.sha256 ? "date unknown" : "unavailable";
		extras.push([iv, note]);
	}

	return [rowInst, extras];
}

/**
 * Installed version for a single version-build and sha; legacy folder allowed.
 */
export function findInstall(
	versionBuild: string,
	sha256: string | undefined,
	installed: InstalledVersion[],
	count: number = 1,
): InstalledVersion | null {
	return matchInstall(
		versionBuild,
		sha256,
		new Map(installed.map((iv) => [iv.folderName, iv])),
		count,
	);
}

/**
 * Find an installed version by its build string.
 */
export function findInstalledByBuild(
	build: string,
	repoName?: string,
): InstalledVersion | null {
	for (const v of listInstalled()) {
		if (v.version.build === build && (!repoName || v.repoName === repoName)) {
			return v;
		}
	}
	return null;
}

/**
 * Scan browsers/ for installed versions, sorted by repo then version descending.
 */
export function listInstalled(): InstalledVersion[] {
	const installed: InstalledVersion[] = [];
	const active = loadConfig().active_version;

	if (!fs.existsSync(BROWSERS_DIR)) return installed;

	for (const repoEntry of fs.readdirSync(BROWSERS_DIR, {
		withFileTypes: true,
	})) {
		if (!repoEntry.isDirectory() || repoEntry.name.startsWith(".")) continue;
		const repoDir = path.join(BROWSERS_DIR, repoEntry.name);

		for (const versionEntry of fs.readdirSync(repoDir, {
			withFileTypes: true,
		})) {
			if (!versionEntry.isDirectory()) continue;
			const versionDir = path.join(repoDir, versionEntry.name);
			const versionJson = path.join(versionDir, "version.json");
			if (!fs.existsSync(versionJson)) continue;

			try {
				const ver = Version.fromPath(versionDir);
				const versionData = JSON.parse(fs.readFileSync(versionJson, "utf-8"));
				const relPath = `browsers/${repoEntry.name}/${versionEntry.name}`;
				installed.push(
					new InstalledVersion({
						repoName: repoEntry.name,
						version: ver,
						path: versionDir,
						isActive: relPath === active,
						isPrerelease: versionData.prerelease ?? false,
						assetId: versionData.asset_id,
						assetSize: versionData.asset_size,
						assetUpdatedAt: versionData.asset_updated_at,
						sha256: versionData.sha256,
						createdAt: versionData.created_at,
					}),
				);
			} catch {
				// Missing/corrupt version.json: not an install we can use.
			}
		}
	}

	installed.sort((a, b) => {
		const byRepo = cmpStr(b.repoName, a.repoName);
		if (byRepo !== 0) return byRepo;
		return b.version.compare(a.version);
	});
	return installed;
}

/**
 * Get the path to the active version, or null if no version is active.
 */
export function getActivePath(): string | null {
	const config = loadConfig();
	const active = config.active_version;

	// A released library launches the build it was released with, whatever
	// happens to be marked active, unless the user explicitly chose otherwise.
	const pin = effectivePin(config);
	if (pin) {
		for (const inst of listInstalled()) {
			if (
				pinMatches(
					pin,
					inst.repoName,
					inst.version.version ?? "",
					inst.version.build,
				)
			) {
				if (active !== inst.relativePath) {
					config.active_version = inst.relativePath;
					saveConfig(config);
				}
				return inst.path;
			}
		}
		return null;
	}

	if (active) {
		const activePath = path.join(INSTALL_DIR, active);
		if (
			fs.existsSync(activePath) &&
			fs.existsSync(path.join(activePath, "version.json"))
		) {
			return activePath;
		}
	}

	// Only auto-select if the user didn't set a channel or pin
	if (!config.channel && !config.pinned) {
		const installed = listInstalled();
		if (installed.length) {
			config.active_version = installed[0].relativePath;
			saveConfig(config);
			return installed[0].path;
		}
	}

	return null;
}

/**
 * Set the active version by its relative path.
 */
export function setActive(relativePath: string): void {
	const config = loadConfig();
	config.active_version = relativePath;
	saveConfig(config);
}

/**
 * Find an installed version by path, build, full version, or repo/build.
 */
export function findInstalledVersion(specifier: string): string | null {
	const installed = listInstalled();
	if (!installed.length) return null;

	const lower = specifier.toLowerCase();

	for (const v of installed) {
		if (
			v.relativePath === specifier ||
			v.relativePath === `browsers/${specifier}`
		) {
			return v.path;
		}
		if (
			`browsers/${v.repoName}/${v.version.fullString}`.endsWith(specifier) ||
			`${v.repoName}/${v.version.build}`.toLowerCase() === lower ||
			v.version.build.toLowerCase() === lower ||
			v.version.fullString.toLowerCase() === lower ||
			v.version.version?.toLowerCase() === lower
		) {
			return v.path;
		}
	}

	return null;
}

/**
 * Install to browsers/{repoName}/{version}-{build}-{sha8}; the suffix is
 * omitted when the release carries no sha.
 */
export async function installVersioned(
	fetcher: CamoufoxFetcher,
	replace: boolean = false,
): Promise<boolean> {
	const repoName = getRepoName(fetcher.githubRepo);
	const sha8 = fetcher._selectedVersion?.sha256
		? fetcher._selectedVersion.sha8
		: fetcher.installedSha8;
	const versionFolder = versionFolderName(fetcher.version, fetcher.build, sha8);
	const installPath = path.join(BROWSERS_DIR, repoName, versionFolder);

	if (
		fs.existsSync(installPath) &&
		fs.existsSync(path.join(installPath, "version.json"))
	) {
		if (!replace) {
			const installedV = findInstalledByBuild(fetcher.build, repoName);
			let changeMsg = "";
			if (installedV && fetcher._selectedVersion) {
				const changes = installedV.getChanges(fetcher._selectedVersion);
				if (changes.length) changeMsg = ` (${changes.join(", ")})`;
			}

			rprint(
				`Version v${fetcher.verstr} already installed${changeMsg}.`,
				"yellow",
			);
			rprint(
				changeMsg
					? "Use --replace to update with the new release."
					: "Use --replace to reinstall.",
				"yellow",
			);
			if (!loadConfig().active_version) {
				setActive(`browsers/${repoName}/${versionFolder}`);
			}
			return false;
		}
		rprint(`Replacing: ${installPath}`, "yellow");
		fs.rmSync(installPath, { recursive: true, force: true });
	}

	const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-"));
	const tempFilePath = path.join(tempDir, "camoufox.zip");

	try {
		fs.mkdirSync(installPath, { recursive: true });

		const tempFileStream = fs.createWriteStream(tempFilePath);
		// finished() listens for the stream's 'error' from the start. Without a
		// listener, a failed write (disk full) is an uncaught 'error' event that
		// kills the process before the catch below can remove the partial
		// install.
		const written = finished(tempFileStream);
		written.catch(() => {}); // awaited below; a download error wins
		try {
			// Through the instance's class, as Python's fetcher.download_file(),
			// so a subclass can override it.
			await (fetcher.constructor as typeof CamoufoxFetcher).downloadFile(
				tempFileStream,
				fetcher.url,
			);
		} finally {
			tempFileStream.end();
		}
		await written;

		const expectedSha = fetcher._selectedVersion
			? fetcher._selectedVersion.sha256
			: fetcher.installedSha256;
		verifySha256(tempFilePath, expectedSha, `Camoufox v${fetcher.verstr}`);

		rprint(`Extracting Camoufox: ${installPath}`);
		unzip(tempFilePath, installPath);

		const metadata = fetcher._selectedVersion
			? fetcher._selectedVersion.toMetadata()
			: {
					version: fetcher.version,
					build: fetcher.build,
					prerelease: fetcher.isPrerelease,
					sha256: fetcher.installedSha256 ?? null,
					created_at: fetcher.installedCreatedAt ?? null,
				};
		fs.writeFileSync(
			path.join(installPath, "version.json"),
			JSON.stringify(metadata),
		);

		if (OS_NAME !== "win") {
			makeExecutable(installPath);
		}

		setActive(`browsers/${repoName}/${versionFolder}`);

		// Mark the install dir as compatible with this version
		fs.writeFileSync(COMPAT_FLAG, "");

		rprint(`\nCamoufox v${fetcher.verstr} installed.`, "green");
		rprint(`Path: ${installPath}`, "green");
		return true;
	} catch (error) {
		rprint(`Error: ${error}`, "red");
		if (fs.existsSync(installPath)) {
			fs.rmSync(installPath, { recursive: true, force: true });
		}
		throw error;
	} finally {
		fs.rmSync(tempDir, { recursive: true, force: true });
	}
}

/**
 * Remove a specific version installation.
 */
export function removeVersion(versionPath: string): boolean {
	if (!fs.existsSync(versionPath)) return false;

	rprint(`Removing: ${versionPath}`);
	fs.rmSync(versionPath, { recursive: true, force: true });

	const parent = path.dirname(versionPath);
	if (
		fs.existsSync(parent) &&
		parent !== BROWSERS_DIR &&
		fs.readdirSync(parent).length === 0
	) {
		fs.rmdirSync(parent);
	}
	if (
		fs.existsSync(BROWSERS_DIR) &&
		fs.readdirSync(BROWSERS_DIR).length === 0
	) {
		fs.rmdirSync(BROWSERS_DIR);
	}

	const config = loadConfig();
	const relPath = path.relative(INSTALL_DIR, versionPath);
	if (!relPath.startsWith("..") && config.active_version === relPath) {
		const remaining = listInstalled();
		config.active_version = remaining.length ? remaining[0].relativePath : null;
		saveConfig(config);
	}

	return true;
}

/**
 * Short tag to tell coexisting installs apart: date, else sha8.
 */
export function installedLabel(iv: InstalledVersion): string {
	if (iv.createdAt) {
		const date = formatAssetDate(iv.createdAt);
		if (date) return date;
	}
	return (iv.sha256 ?? "").slice(0, 8);
}

/**
 * Print installed versions as a tree.
 */
export function printTree(
	showHeader: boolean = true,
	showPaths: boolean = false,
): void {
	const installed = listInstalled();

	if (!installed.length) {
		rprint("No versions installed.", "yellow");
		rprint("Run `camoufox fetch` to install.", "yellow");
		return;
	}

	if (showHeader) {
		rprint("Installed versions:\n", "yellow");
	}

	let currentRepo: string | null = null;
	for (let i = 0; i < installed.length; i++) {
		const v = installed[i];
		const isLast =
			i === installed.length - 1 || installed[i + 1].repoName !== v.repoName;

		if (v.repoName !== currentRepo) {
			currentRepo = v.repoName;
			rprint(`${currentRepo}/`, "cyan", false);
			if (showPaths) {
				rprint(` -> ${path.join(BROWSERS_DIR, currentRepo)}`, "bright_black");
			} else {
				rprint("");
			}
		}

		rprint(`    ${isLast ? "└── " : "├── "}`, undefined, false);
		rprint(`v${v.version.fullString}`, v.isActive ? "green" : undefined, false);
		rprint(
			v.isPrerelease ? " (prerelease)" : " (stable)",
			v.isPrerelease ? "yellow" : "blue",
			false,
		);
		const tag = installedLabel(v);
		if (tag) rprint(` (${tag})`, "bright_black", false);
		if (v.isActive) rprint(" (active)", "green", false);
		rprint("");
	}
}
