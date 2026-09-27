#!/usr/bin/env node
/**
 * The `camoufox` CLI.
 *
 * TypeScript twin of pythonlib/camoufox/__main__.py. Every command is present,
 * with the same arguments, output and config/cache files. `gui` drives a
 * PySide6 desktop app with no Node equivalent, so here it only says so. The
 * interactive pickers (`set`, `set --geoip`, `remove --select`) use a numbered
 * prompt in place of inquirer's arrow-key list.
 */
import * as fs from "node:fs";
import { createRequire } from "node:module";
import * as path from "node:path";
import * as readline from "node:readline";
import { Argument, Command, Option } from "commander";
import { LIBRARY_VERSION } from "./__version__.js";
import { DefaultAddons, maybeDownloadAddons } from "./addons.js";
import { FileNotFoundError } from "./exceptions.js";
import {
	allowGeoip,
	downloadMmdb,
	GEOIP_DIR,
	type GeoIPRepo,
	getMmdbPath,
	loadGeoipConfig,
	saveGeoipConfig,
} from "./geolocation.js";
import {
	BROWSERS_DIR,
	type CachedVersion,
	COMPAT_FLAG,
	CONFIG_FILE,
	findInstall,
	getDefaultChannel,
	type InstalledVersion,
	installedLabel,
	latestPerBuild,
	listInstalled,
	loadConfig,
	loadRepoCache,
	printTree,
	REPO_CACHE_FILE,
	type RepoCache,
	removeVersion,
	saveConfig,
	saveRepoCache,
} from "./multiversion.js";
import {
	AvailableVersion,
	CamoufoxFetcher,
	formatAssetDate,
	INSTALL_DIR,
	installedVerStr,
	listAvailableVersions,
	loadYaml,
	RepoConfig,
	rprint,
	Version,
} from "./pkgman.js";

// --------------------------------------------------------------------------
// click-style output + prompts
// --------------------------------------------------------------------------

const ANSI: Record<string, string> = {
	red: "31",
	green: "32",
	yellow: "33",
	blue: "34",
	cyan: "36",
	bright_black: "90",
};

function useColor(): boolean {
	return Boolean(process.stdout.isTTY) && !process.env.NO_COLOR;
}

/** click.style */
function style(
	text: string,
	{ fg, bold, dim }: { fg?: string | null; bold?: boolean; dim?: boolean } = {},
): string {
	if (!useColor()) return text;
	const codes: string[] = [];
	if (bold) codes.push("1");
	if (dim) codes.push("2");
	if (fg && ANSI[fg]) codes.push(ANSI[fg]);
	return codes.length ? `\x1b[${codes.join(";")}m${text}\x1b[0m` : text;
}

/** click.secho */
function secho(
	text: string,
	opts: { fg?: string | null; bold?: boolean; nl?: boolean } = {},
): void {
	process.stdout.write(style(text, opts) + (opts.nl === false ? "" : "\n"));
}

/** click.echo */
function echo(text = "", nl = true): void {
	process.stdout.write(text + (nl ? "\n" : ""));
}

let rl: readline.Interface | null = null;
const pendingLines: string[] = [];
const lineWaiters: Array<(line: string | null) => void> = [];
let stdinClosed = false;

function readLine(): Promise<string | null> {
	if (!rl) {
		rl = readline.createInterface({ input: process.stdin });
		rl.on("line", (line) => {
			const waiter = lineWaiters.shift();
			if (waiter) waiter(line);
			else pendingLines.push(line);
		});
		rl.on("close", () => {
			stdinClosed = true;
			for (const waiter of lineWaiters.splice(0)) waiter(null);
		});
	}
	const queued = pendingLines.shift();
	if (queued !== undefined) return Promise.resolve(queued);
	if (stdinClosed) return Promise.resolve(null);
	return new Promise((resolve) => lineWaiters.push(resolve));
}

function closePrompts(): void {
	rl?.close();
	rl = null;
}

/** click.confirm (default No). EOF answers No. */
async function confirm(message: string): Promise<boolean> {
	for (;;) {
		process.stdout.write(`${message} [y/N]: `);
		const answer = await readLine();
		if (answer === null) {
			echo();
			return false;
		}
		const value = answer.trim().toLowerCase();
		if (value === "") return false;
		if (value === "y" || value === "yes") return true;
		if (value === "n" || value === "no") return false;
		echo("Error: invalid input");
	}
}

/**
 * Generic selection, standing in for the Python twin's inquirer list.
 * Returns the selected value, or null on cancel/EOF.
 */
async function select<T>(
	choices: Array<[string, T]>,
	message: string,
): Promise<T | null> {
	echo(`${style("[?]", { fg: "yellow" })} ${message}:`);
	choices.forEach(([label], i) => {
		echo(`  ${style(String(i + 1).padStart(2), { fg: "cyan" })}) ${label}`);
	});
	for (;;) {
		process.stdout.write(`Choice [1-${choices.length}]: `);
		const answer = await readLine();
		if (answer === null || answer.trim() === "") {
			if (answer === null) echo();
			return null;
		}
		const n = Number.parseInt(answer.trim(), 10);
		if (Number.isInteger(n) && n >= 1 && n <= choices.length) {
			return choices[n - 1][1];
		}
		echo(`Error: enter a number between 1 and ${choices.length}`);
	}
}

// --------------------------------------------------------------------------
// helpers
// --------------------------------------------------------------------------

/** Find an installed version by channel path, build, or full version string. */
function findInstalled(specifier: string): InstalledVersion | null {
	const spec = specifier.toLowerCase();
	const installed = listInstalled();
	const parts = spec.split("/");

	for (const v of installed) {
		if (
			v.channelPath.toLowerCase() === spec ||
			v.relativePath.toLowerCase() === spec ||
			v.version.build.toLowerCase() === spec ||
			v.version.fullString.toLowerCase() === spec
		) {
			return v;
		}
		// Match repo/version without channel, for example official/134.0.2-beta.20
		if (parts.length === 2) {
			const [repo, ver] = parts;
			if (v.repoName === repo && v.version.fullString.toLowerCase() === ver) {
				return v;
			}
		}
	}

	// Match repo/channel, for example official/stable gets the latest installed
	// for that channel
	if (parts.length === 2) {
		const [repo, ctype] = parts;
		if (ctype === "stable" || ctype === "prerelease") {
			const isPre = ctype === "prerelease";
			for (const v of installed) {
				if (v.repoName === repo && v.isPrerelease === isPre) return v;
			}
		}
	}

	return null;
}

/** Name of the active GeoIP source. */
function getGeoIPSourceName(): string {
	try {
		return loadGeoipConfig().name ?? "Default";
	} catch {
		return "Default";
	}
}

/**
 * Sync available versions from the remote repositories. Returns true on success.
 */
async function doSync(spoofOs?: string, spoofArch?: string): Promise<boolean> {
	rprint("Syncing repositories...", "yellow");

	const cache: {
		repos: Array<{ name: string; repo: string; versions: CachedVersion[] }>;
		spoof_os: string | null;
		spoof_arch: string | null;
	} = {
		repos: [],
		spoof_os: spoofOs ?? null,
		spoof_arch: spoofArch ?? null,
	};

	for (const repoConfig of RepoConfig.loadRepos()) {
		rprint(`  ${repoConfig.name}...`, "cyan", false);
		try {
			const versions = await listAvailableVersions(
				repoConfig,
				true,
				spoofOs,
				spoofArch,
			);
			cache.repos.push({
				name: repoConfig.name,
				repo: repoConfig.repo,
				versions: versions.map(
					(v) =>
						({
							version: v.version.version ?? null,
							build: v.version.build,
							url: v.url,
							is_prerelease: v.isPrerelease,
							asset_id: v.assetId ?? null,
							asset_size: v.assetSize ?? null,
							asset_updated_at: v.assetUpdatedAt ?? null,
							sha256: v.sha256 ?? null,
							created_at: v.assetCreatedAt ?? null,
						}) as unknown as CachedVersion,
				),
			});
			rprint(` ${versions.length} versions`, "green");
		} catch (e) {
			rprint(` Error: ${errorMessage(e)}`, "red");
		}
	}

	saveRepoCache(cache as RepoCache);
	const total = cache.repos.reduce((sum, r) => sum + r.versions.length, 0);
	const platformStr = spoofOs ? ` (${spoofOs}/${spoofArch})` : "";
	rprint(
		`\nSynced ${total} versions from ${cache.repos.length} repos${platformStr}.`,
		"green",
	);

	return true;
}

function errorMessage(e: unknown): string {
	return e instanceof Error ? e.message : String(e);
}

/** Ensure a repo cache exists. Returns true if synced. */
function ensureSynced(): boolean {
	if (!fs.existsSync(REPO_CACHE_FILE)) {
		rprint("No repo cache found. Run 'camoufox sync' first.", "red");
		return false;
	}
	return true;
}

type RepoBlock = { name: string; versions?: CachedVersion[] };

/** Cache block for a repo by name. */
function repoData(cache: RepoCache, repoName: string): RepoBlock | null {
	return (
		(cache.repos ?? []).find(
			(r) => r.name.toLowerCase() === repoName.toLowerCase(),
		) ?? null
	);
}

/**
 * Resolve a version-build or version-build-sha8 spec against cache entries.
 * Returns [asset, sha] for a specific date, [latest, null] to follow the
 * latest, or [null, null] when the spec is unknown.
 */
function resolveSpec(
	repo: RepoBlock,
	spec: string,
): [CachedVersion | null, string | null] {
	const versions = repo.versions ?? [];
	for (const v of versions) {
		const sha = v.sha256 || "";
		if (sha && spec === `${v.version}-${v.build}-${sha.slice(0, 8)}`) {
			return [v, sha];
		}
	}
	for (const v of latestPerBuild(versions)) {
		if (spec === `${v.version}-${v.build}`) return [v, null];
	}
	return [null, null];
}

/** Cache entry a pin resolves to: the specific sha asset or the build's latest. */
function pinTarget(
	repo: RepoBlock,
	pinned: string,
	pinnedSha?: string | null,
): CachedVersion | null {
	const versions = repo.versions ?? [];
	if (pinnedSha) {
		return versions.find((v) => v.sha256 === pinnedSha) ?? null;
	}
	return (
		latestPerBuild(versions).find(
			(v) => `${v.version}-${v.build}` === pinned,
		) ?? null
	);
}

/** Set to track a channel (fetches the latest on fetch). */
function setChannel(repoName: string, channelType: string): void {
	const config = loadConfig();
	config.channel = `${repoName}/${channelType}`;
	delete config.pinned;
	delete config.pinned_sha;

	// Check if the latest for this channel is already installed
	const isPre = channelType === "prerelease";
	const cache = loadRepoCache();
	for (const repo of cache.repos ?? []) {
		if (repo.name.toLowerCase() !== repoName.toLowerCase()) continue;
		const candidates = (repo.versions ?? []).filter(
			(v) => (v.is_prerelease ?? false) === isPre,
		);
		if (candidates.length) {
			const latestBuild = candidates[0].build;
			for (const inst of listInstalled()) {
				if (
					inst.version.build === latestBuild &&
					inst.repoName === repoName.toLowerCase()
				) {
					config.active_version = inst.relativePath;
					saveConfig(config);
					secho(`Channel: ${repoName.toLowerCase()}/${channelType}`, {
						fg: "cyan",
						bold: true,
					});
					secho(`Using latest: ${inst.channelPath} (installed)`, {
						fg: "green",
					});
					return;
				}
			}
		}
		break;
	}

	delete config.active_version;
	saveConfig(config);
	secho(`Channel: ${repoName.toLowerCase()}/${channelType}`, {
		fg: "cyan",
		bold: true,
	});
	secho("Run 'camoufox fetch' to install latest.", { fg: "yellow" });
}

/** Pin a version-build, optionally to a specific dated asset by sha. */
function setPinned(
	repoName: string,
	channelType: string,
	verData: CachedVersion,
	inst: InstalledVersion | null,
	sha?: string | null,
): void {
	const config = loadConfig();
	config.channel = `${repoName.toLowerCase()}/${channelType}`;
	config.pinned = `${verData.version}-${verData.build}`;
	if (sha) {
		config.pinned_sha = sha;
	} else {
		delete config.pinned_sha;
	}
	const tag = sha ? ` (${sha.slice(0, 8)})` : "";
	const display = `${repoName.toLowerCase()}/${channelType}/${verData.version}-${verData.build}${tag}`;
	if (inst) {
		config.active_version = inst.relativePath;
		saveConfig(config);
		secho(`Pinned: ${display} (installed)`, { fg: "green" });
	} else {
		delete config.active_version;
		saveConfig(config);
		secho(`Pinned: ${display}`, { fg: "cyan", bold: true });
		secho("Run 'camoufox fetch' to install.", { fg: "yellow" });
	}
}

/**
 * Checks & updates Camoufox.
 */
class CamoufoxUpdate extends CamoufoxFetcher {
	currentVerStr: string | null = null;

	async init(): Promise<this> {
		await super.init();
		try {
			this.currentVerStr = installedVerStr();
		} catch (error) {
			if (!(error instanceof FileNotFoundError)) throw error;
			this.currentVerStr = null;
		}
		return this;
	}

	isUpdatedNeeded(): boolean {
		return this.currentVerStr === null || this.currentVerStr !== this.verstr;
	}

	async update(replace = false, iKnowWhatImDoing = false): Promise<void> {
		if (!this.isUpdatedNeeded() && !replace) {
			rprint("Camoufox binaries up to date!", "green");
			rprint(`Current version: v${this.currentVerStr}`, "green");
			return;
		}

		if (this.isPrerelease && !iKnowWhatImDoing) {
			rprint(`Warning: v${this.verstr} is a prerelease version!`, "yellow");
			if (!(await confirm("Continue with prerelease installation?"))) {
				rprint("Installation cancelled.", "red");
				return;
			}
		}

		const action = this.currentVerStr ? "Installing" : "Fetching";
		rprint(`${action} Camoufox v${this.verstr}...`, "yellow");
		await this.install(replace);
	}
}

// --------------------------------------------------------------------------
// commands
// --------------------------------------------------------------------------

const program = new Command();
program.name("camoufox").version(LIBRARY_VERSION);

program
	.command("sync")
	.description("Sync available versions from remote repositories")
	.addOption(
		new Option("--spoof-os <os>", "Spoof OS (auto = native)").choices([
			"auto",
			"mac",
			"win",
			"lin",
		]),
	)
	.addOption(
		new Option(
			"--spoof-arch <arch>",
			"Spoof architecture (auto = native)",
		).choices(["auto", "x86_64", "i686", "arm64"]),
	)
	.action(async ({ spoofOs, spoofArch }) => {
		await doSync(
			spoofOs === "auto" ? undefined : spoofOs,
			spoofArch === "auto" ? undefined : spoofArch,
		);
	});

program
	.command("fetch")
	.description("Install the active version, or a specific version")
	.argument("[version]", "e.g. official/135.0-beta.25")
	.action(async (version?: string) => {
		// Clean up an incompatible old data directory
		if (
			fs.existsSync(INSTALL_DIR) &&
			fs.readdirSync(INSTALL_DIR).length > 0 &&
			!fs.existsSync(COMPAT_FLAG)
		) {
			rprint("Cleaning old data...", "yellow");
			fs.rmSync(INSTALL_DIR, { recursive: true, force: true });
		}

		await doSync();

		const cache = loadRepoCache();
		const config = loadConfig();

		let repoName: string | null = null;
		let repo: RepoBlock | null = null;
		let verData: CachedVersion | null = null;

		if (version) {
			const parts = version.toLowerCase().split("/");
			let spec: string;
			if (parts.length === 1) {
				repoName = RepoConfig.getDefaultName();
				spec = parts[0];
			} else if (parts.length === 2 || parts.length === 3) {
				repoName = parts[0];
				spec = parts[parts.length - 1];
			} else {
				rprint(
					"Format: version-build, repo/version-build, or repo/channel/version-build",
					"red",
				);
				return;
			}
			repo = repoData(cache, repoName);
			if (repo) [verData] = resolveSpec(repo, spec.replace(/^v+/, ""));
		} else if (config.pinned) {
			const channel = config.channel ?? "";
			repoName = channel.includes("/") ? channel.split("/")[0] : channel;
			repo = repoData(cache, repoName);
			if (repo) verData = pinTarget(repo, config.pinned, config.pinned_sha);
		} else {
			const channel = config.channel || getDefaultChannel();
			const slash = channel.indexOf("/");
			const name = slash === -1 ? channel : channel.slice(0, slash);
			const ctype = slash === -1 ? "stable" : channel.slice(slash + 1);
			repoName = name;
			repo = repoData(cache, repoName);
			if (repo) {
				const isPre = ctype === "prerelease";
				const latest = latestPerBuild(repo.versions ?? []).filter(
					(v) => (v.is_prerelease ?? false) === isPre,
				);
				verData = latest[0] ?? null;
			}
		}

		if (!verData || !repo) {
			rprint(
				`Version '${version || repoName}' not found in cache. Run 'camoufox sync'.`,
				"red",
			);
			return;
		}

		const selected = new AvailableVersion({
			version: new Version(verData.build, verData.version),
			url: verData.url,
			isPrerelease: verData.is_prerelease ?? false,
			sha256: verData.sha256 ?? undefined,
			assetCreatedAt: verData.created_at ?? undefined,
		});
		const repoConfig = RepoConfig.findByName(repo.name);
		try {
			const updater = await new CamoufoxUpdate(repoConfig, selected).init();
			await updater.update();
		} catch (e) {
			const msg = errorMessage(e);
			if (msg.includes("404") || msg.includes("Not Found")) {
				rprint("Release not found (404). Asset may have been removed.", "red");
				rprint("Run 'camoufox sync' to refresh available versions.", "yellow");
			} else {
				rprint(`Error: ${msg}`, "red");
			}
			return;
		}
		if (allowGeoip()) {
			await downloadMmdb();
		}
		await maybeDownloadAddons({ ...DefaultAddons });
		// TS addition: Python's fpgen package ships its model with the wheel;
		// the TS port fetches the pinned model into the cache, so do it here
		// rather than on the first launch.
		const { ensureModel } = await import("./fpgen/index.js");
		await ensureModel();
	});

program
	.command("set")
	.description(
		"Set the active Camoufox version to use & fetch.\n" +
			"By default, this opens an interactive selector for versions and settings.\n" +
			"You can also pass a specifier to activate directly:\n" +
			"Pin version:\n" +
			"    camoufox set official/stable/134.0.2-beta.20\n" +
			"Automatically find latest in a channel source:\n" +
			"    camoufox set official/stable",
	)
	.argument("[specifier]")
	.option("--geoip", "Select GeoIP source instead")
	.action(async (specifier: string | undefined, { geoip }) => {
		if (geoip) {
			await selectGeoIPSource();
			return;
		}

		if (specifier) {
			const parts = specifier.toLowerCase().split("/");

			// 2-part sets a channel like official/stable
			if (parts.length === 2) {
				const [repoName, ctype] = parts;
				if (ctype !== "stable" && ctype !== "prerelease") {
					rprint(
						`Unknown channel type '${ctype}'. Use 'stable' or 'prerelease'.`,
						"red",
					);
					return;
				}
				setChannel(repoName, ctype);
				return;
			}

			// 1-part pins in the default repo, 3-part names the repo and channel
			let repoName: string;
			let spec: string;
			if (parts.length === 1) {
				repoName = RepoConfig.getDefaultName();
				spec = parts[0];
			} else if (parts.length === 3) {
				const ctype = parts[1];
				[repoName, , spec] = parts;
				if (ctype !== "stable" && ctype !== "prerelease") {
					rprint(
						`Unknown channel type '${ctype}'. Use 'stable' or 'prerelease'.`,
						"red",
					);
					return;
				}
			} else {
				rprint(`Invalid specifier '${specifier}'.`, "red");
				rprint(
					"Use: version-build, repo/channel, or repo/channel/version-build",
					"yellow",
				);
				return;
			}

			if (!ensureSynced()) return;
			const repo = repoData(loadRepoCache(), repoName);
			if (!repo) {
				rprint(
					`Repo '${repoName.toLowerCase()}' not in cache. Run 'camoufox sync'.`,
					"red",
				);
				return;
			}
			const [verData, sha] = resolveSpec(repo, spec.replace(/^v+/, ""));
			if (!verData) {
				rprint(
					`Version '${spec}' not found in ${repoName.toLowerCase()}.`,
					"red",
				);
				return;
			}
			const ctype = verData.is_prerelease ? "prerelease" : "stable";
			const vb = `${verData.version}-${verData.build}`;
			const count = (repo.versions ?? []).filter(
				(x) => `${x.version}-${x.build}` === vb,
			).length;
			const inst = findInstall(vb, verData.sha256, listInstalled(), count);
			setPinned(repo.name, ctype, verData, inst, sha);
			return;
		}

		if (!ensureSynced()) return;
		await interactiveSet();
	});

async function interactiveSet(): Promise<void> {
	const cache = loadRepoCache();
	const installedList = listInstalled();

	if (!cache.repos?.length) {
		rprint("No versions in cache. Run 'camoufox sync' first.", "red");
		return;
	}

	const channels: Array<[string, string, CachedVersion]> = [];
	for (const repo of cache.repos) {
		const versions = repo.versions ?? [];
		const stable = latestPerBuild(versions.filter((v) => !v.is_prerelease));
		const prereleases = latestPerBuild(versions.filter((v) => v.is_prerelease));
		if (stable.length) channels.push([repo.name, "stable", stable[0]]);
		if (prereleases.length) {
			channels.push([repo.name, "prerelease", prereleases[0]]);
		}
	}

	const config = loadConfig();
	const channel = config.channel || getDefaultChannel();
	const pinned = config.pinned;
	const pinnedSha = config.pinned_sha;

	if (pinned) {
		secho(`Pinned: ${channel.toLowerCase()}/${pinned}`, { fg: "cyan" });
	} else {
		secho(`Channel: ${channel.toLowerCase()}`, { fg: "cyan" });
	}
	echo();

	// Full dated lists so the pin picker can show every date, not just the latest
	const channelVersions: Array<[string, string, CachedVersion[]]> = [];
	for (const repo of cache.repos) {
		const versions = repo.versions ?? [];
		const stable = versions.filter((v) => !v.is_prerelease);
		const prereleases = versions.filter((v) => v.is_prerelease);
		if (stable.length) channelVersions.push([repo.name, "stable", stable]);
		if (prereleases.length) {
			channelVersions.push([repo.name, "prerelease", prereleases]);
		}
	}

	type Action = "channel" | "exit" | ["pin", string, string, CachedVersion[]];

	for (;;) {
		const choices: Array<[string, Action]> = [["Set channel", "channel"]];
		for (const [name, ctype, versions] of channelVersions) {
			const label = `Pin version: ${style(`${name.toLowerCase()}/${ctype}`, { fg: "cyan", bold: true })}`;
			choices.push([label, ["pin", name, ctype, versions]]);
		}
		choices.push([style("Exit", { fg: "bright_black" }), "exit"]);

		const action = await select(choices, "Select");
		if (action === null || action === "exit") return;

		if (action === "channel") {
			const chChoices: Array<[string, [string, string] | null]> = [];
			for (const [name, ctype, latest] of channels) {
				const verStr = `v${latest.version}-${latest.build}`;
				const isCurrent = channel === `${name}/${ctype}`;
				let label = `${name.toLowerCase()}/${ctype} (latest: ${verStr})`;
				if (isCurrent) {
					label = `${style(label, { fg: "green", bold: true })} (current)`;
				}
				chChoices.push([label, [name, ctype]]);
			}
			chChoices.push([style("Back", { fg: "bright_black" }), null]);

			const chAnswer = await select(chChoices, "Set channel");
			if (!chAnswer) continue;
			setChannel(chAnswer[0], chAnswer[1]);
			return;
		}

		const [, rname, ctype, versions] = action;
		const vbCounts = new Map<string, number>();
		for (const x of versions) {
			const key = `${x.version}-${x.build}`;
			vbCounts.set(key, (vbCounts.get(key) ?? 0) + 1);
		}

		const vChoices: Array<[string, CachedVersion | null]> = [];
		for (const v of versions) {
			const vb = `${v.version}-${v.build}`;
			const sha = v.sha256 || "";
			const date = formatAssetDate(v.created_at ?? undefined);
			const inst = findInstall(
				vb,
				v.sha256 ?? undefined,
				installedList,
				vbCounts.get(vb) ?? 0,
			);
			const isPinned = pinned === vb && (pinnedSha ?? null) === (sha || null);
			let color: string | null;
			let bold: boolean;
			let status: string;
			if (isPinned) {
				[color, bold, status] = ["green", true, "(pinned)"];
			} else if (inst) {
				[color, bold, status] = [null, false, "(installed)"];
			} else {
				[color, bold, status] = ["bright_black", false, ""];
			}
			const cells = [date, sha ? `(${sha.slice(0, 8)})` : "", status].filter(
				Boolean,
			);
			const meta = cells.length ? `  ${cells.join("  ")}` : "";
			vChoices.push([style(`v${vb}`, { fg: color, bold }) + meta, v]);
		}
		vChoices.push([style("Back", { fg: "bright_black" }), null]);

		const verData = await select(
			vChoices,
			`Pin version (${rname.toLowerCase()}/${ctype})`,
		);
		if (!verData) continue;

		const vb = `${verData.version}-${verData.build}`;
		const inst = findInstall(
			vb,
			verData.sha256 ?? undefined,
			installedList,
			vbCounts.get(vb) ?? 0,
		);
		setPinned(rname, ctype, verData, inst, verData.sha256);
		return;
	}
}

/** Interactive selection of the GeoIP source. */
async function selectGeoIPSource(): Promise<void> {
	const repos: GeoIPRepo[] = loadYaml("repos.yml").geoip ?? [];
	if (!repos.length) {
		rprint("No GeoIP sources configured.", "red");
		return;
	}

	let current = "";
	try {
		current = loadGeoipConfig().name ?? "";
	} catch {
		// unreadable config: nothing is marked active
	}
	const choices: Array<[string, GeoIPRepo]> = repos.map((r) => [
		r.name + (r.name === current ? " [active]" : ""),
		r,
	]);

	const selected = await select(choices, "Select GeoIP source");
	if (!selected) return;

	saveGeoipConfig(selected);
	rprint(`GeoIP source: ${selected.name}`, "green");
}

program
	.command("list")
	.description(
		"List Camoufox versions\n\n" +
			"installed  Show installed versions (default)\n" +
			"all        Show all available versions from synced repos",
	)
	.addArgument(
		new Argument("[mode]").choices(["installed", "all"]).default("installed"),
	)
	.option("--path", "Show full paths")
	.action((mode: string, { path: showPaths }: { path?: boolean }) => {
		if (mode === "all") {
			listAll(Boolean(showPaths));
		} else {
			listInstalledVersions(Boolean(showPaths));
		}
	});

function listInstalledVersions(showPaths: boolean): void {
	printTree(true, showPaths);

	echo();
	secho("geoip/", { fg: "cyan", bold: true, nl: false });
	if (showPaths && fs.existsSync(GEOIP_DIR)) {
		secho(` -> ${GEOIP_DIR}`, { fg: "bright_black" });
	} else {
		echo();
	}

	if (fs.existsSync(GEOIP_DIR)) {
		const mmdb = getMmdbPath();
		if (fs.existsSync(mmdb)) {
			echo(`    └── ${path.basename(mmdb)} `, false);
			secho(`(${getGeoIPSourceName()})`, { fg: "green" });
		} else {
			rprint("    └── Not downloaded", "yellow");
		}
	} else {
		rprint("    └── Not configured", "yellow");
	}
}

function listAll(showPaths: boolean): void {
	if (!ensureSynced()) return;

	const cache = loadRepoCache();
	const installed = new Map(listInstalled().map((v) => [v.version.build, v]));

	rprint("Available versions:\n", "yellow");

	for (const repo of cache.repos ?? []) {
		const versions = latestPerBuild(repo.versions ?? []);

		secho(`${repo.name}/`, { fg: "cyan", bold: true });

		versions.forEach((v, i) => {
			const fullVer = `${v.version}-${v.build}`;
			const inst = installed.get(v.build);
			const isLast = i === versions.length - 1;
			const prefix = isLast ? "└── " : "├── ";
			const active = Boolean(inst?.isActive);

			echo(`    ${prefix}`, false);
			secho(`v${fullVer}`, {
				fg: active ? "green" : null,
				bold: active,
				nl: false,
			});

			if (v.is_prerelease) {
				secho(" (prerelease)", { fg: "yellow", nl: false });
			} else {
				secho(" (stable)", { fg: "blue", nl: false });
			}

			if (inst) {
				if (inst.isActive) {
					secho(" (installed, active)", { fg: "green", bold: true, nl: false });
				} else {
					secho(" (installed)", { fg: "green", nl: false });
				}
				if (showPaths) {
					secho(` -> ${inst.path}`, { fg: "bright_black", nl: false });
				}
			}

			echo();
		});

		echo();
	}
}

program
	.command("remove")
	.description(
		"Remove downloaded data. By default, this removes everything.\n" +
			"Pass --select to pick a browser version to remove.",
	)
	.argument("[version_path]")
	.option("--select", "Interactively select a version to remove")
	.option("-y, --yes", "Skip confirmation prompts")
	.action(
		async (
			versionPath: string | undefined,
			{ select: doSelect, yes }: { select?: boolean; yes?: boolean },
		) => {
			// Select mode: interactively pick a single version
			if (doSelect) {
				const installed = listInstalled();
				if (!installed.length) {
					rprint("No browser versions installed.", "yellow");
					return;
				}
				const choices: Array<[string, InstalledVersion]> = installed.map(
					(v) => {
						const tag = installedLabel(v);
						const suffix = tag ? ` (${tag})` : "";
						return [
							v.channelPath + suffix + (v.isActive ? " [active]" : ""),
							v,
						];
					},
				);
				const target = await select(choices, "Select version to remove");
				if (!target) {
					rprint("Cancelled.", "yellow");
					return;
				}
				if (yes || (await confirm(`Remove ${target.channelPath}?`))) {
					removeVersion(target.path);
					rprint(`Removed ${target.channelPath}`, "green");
				}
				return;
			}

			// Specific version: remove just that one
			if (versionPath) {
				const target = findInstalled(versionPath);
				if (!target) {
					rprint(`Version '${versionPath}' not found.`, "red");
					return;
				}
				if (yes || (await confirm(`Remove ${target.channelPath}?`))) {
					removeVersion(target.path);
					rprint(`Removed ${target.channelPath}`, "green");
				}
				return;
			}

			// Default: remove everything
			if (
				!fs.existsSync(INSTALL_DIR) ||
				fs.readdirSync(INSTALL_DIR).length === 0
			) {
				rprint("Nothing to remove.", "yellow");
				return;
			}

			if (
				yes ||
				(await confirm(`Remove the camoufox data directory (${INSTALL_DIR})?`))
			) {
				fs.rmSync(INSTALL_DIR, { recursive: true, force: true });
				rprint("Removed camoufox data directory.", "green");
			}
		},
	);

program
	.command("test")
	.description("Open the Playwright inspector")
	.argument("[url]")
	.option("--executable-path <path>", "Path to the Camoufox executable")
	.action(async (url: string | undefined, { executablePath }) => {
		const { Camoufox } = await import("./sync_api.js");
		const browser = await Camoufox({
			headless: false,
			env: process.env as Record<string, string>,
			config: { showcursor: false },
			executable_path: executablePath,
		});
		try {
			const page = await browser.newPage();
			if (url) {
				await page.goto(url);
			}
			await page.pause();
		} finally {
			await browser.close();
		}
	});

program
	.command("server")
	.description("Launch a Playwright server")
	.action(async () => {
		// The Python twin hands launch options to launchServer.js, which logs
		// exactly this; the server runs until the process is told to stop.
		const { launchServer } = await import("./server.js");
		const started = performance.now();
		console.info("Launching server...");
		const server = await launchServer();
		console.log(
			`Server launched: ${(performance.now() - started).toFixed(3)}ms`,
		);
		console.log("Websocket endpoint:\x1b[93m", server.wsEndpoint(), "\x1b[0m");

		await new Promise<void>((resolve) => {
			const stop = () => resolve();
			process.once("SIGINT", stop);
			process.once("SIGTERM", stop);
		});
		await server.close();
	});

program
	.command("gui")
	.description("Launch the Camoufox Manager GUI (requires PySide6)")
	.option("--debug", "Enable debug options in the GUI.")
	.action(() => {
		rprint(
			"The GUI is a PySide6 app and is only available from the Python package: pip install 'camoufox[gui]'",
			"red",
		);
	});

// --------------------------------------------------------------------------
// version
// --------------------------------------------------------------------------

/** Version of an installed npm package, or null. */
function pkgVersion(name: string): string | null {
	try {
		const require = createRequire(import.meta.url);
		const pkg = JSON.parse(
			fs.readFileSync(require.resolve(`${name}/package.json`), "utf-8"),
		);
		return typeof pkg.version === "string" ? pkg.version : null;
	} catch {
		return null;
	}
}

/** The TypeScript fpgen port's version, when it exposes one. */
async function fpgenVersion(): Promise<string | null> {
	const specifier = "./fpgen/index.js";
	try {
		const mod: Record<string, unknown> = await import(specifier);
		for (const key of ["VERSION", "version", "__version__", "FPGEN_VERSION"]) {
			if (typeof mod[key] === "string") return mod[key] as string;
		}
		return null;
	} catch {
		return null;
	}
}

class VersionInfo {
	rows: Array<
		[string, string, { fg?: string; bold?: boolean; dim?: boolean }]
	> = [];

	row(label: string, value: string, fg: string | "dim" = "green"): void {
		this.rows.push([
			style(`  ${label}`, { dim: true }),
			value,
			fg === "dim" ? { dim: true } : { fg },
		]);
	}

	header(title: string): void {
		this.rows.push([style(title, { bold: true }), "", {}]);
	}

	pkg(label: string, version: string | null): void {
		if (version) this.row(label, `v${version}`);
		else this.row(label, "?", "dim");
	}

	async packages(): Promise<void> {
		this.header("Packages");
		this.pkg("Camoufox", LIBRARY_VERSION);
		this.pkg("fpgen", await fpgenVersion());
		this.pkg("Playwright", pkgVersion("playwright-core"));
	}

	browser(): void {
		this.header("Browser");

		const config = loadConfig();
		const pinned = config.pinned;
		const channel = config.channel || getDefaultChannel();

		// Active: what was set (channel or pinned version)
		if (pinned) {
			this.row("Active", `${channel.toLowerCase()}/${pinned}`);
		} else {
			this.row("Active", channel.toLowerCase());
		}

		// Find the active installed version
		const activeV = listInstalled().find((v) => v.isActive) ?? null;

		if (activeV) {
			this.row("Current browser", `v${activeV.version.fullString}`);
		} else {
			this.row("Current browser", "Not installed", "dim");
		}

		if (activeV?.createdAt) {
			this.row("Build date", formatAssetDate(activeV.createdAt), "dim");
		}
		if (activeV?.sha256) {
			this.row("SHA256", activeV.sha256.slice(0, 12), "dim");
		}

		if (activeV) {
			this.row("Installed", "Yes", "green");
		} else {
			this.row("Installed", "No", "red");
		}

		// Check if the installed version is the latest in its own channel
		if (activeV) {
			const ctype = activeV.isPrerelease ? "prerelease" : "stable";
			const repoCh = `${activeV.repoName}/${ctype}`;
			let isLatest = false;
			for (const repo of loadRepoCache().repos ?? []) {
				if (repo.name.toLowerCase() !== activeV.repoName.toLowerCase()) {
					continue;
				}
				const candidates = (repo.versions ?? []).filter(
					(v) => (v.is_prerelease ?? false) === activeV.isPrerelease,
				);
				if (
					candidates.length &&
					activeV.version.build === candidates[0].build
				) {
					isLatest = true;
				}
				break;
			}
			this.row(
				`Latest in ${repoCh}?`,
				isLatest ? "Yes" : "No",
				isLatest ? "green" : "red",
			);
		}

		// Last repo sync time from the cache file mtime
		if (fs.existsSync(REPO_CACHE_FILE)) {
			this.row(
				"Last Sync",
				localTimestamp(fs.statSync(REPO_CACHE_FILE).mtime),
				"dim",
			);
		} else {
			this.row("Last Sync", "Never", "red");
		}
	}

	geoip(): void {
		this.header("GeoIP");
		if (!allowGeoip()) {
			this.row("Status", "Not supported (install camoufox[geoip])", "dim");
			return;
		}
		const mmdbPath = getMmdbPath();
		if (fs.existsSync(mmdbPath)) {
			this.row("Database", loadGeoipConfig().name ?? "Unknown");
			this.row("Updated", localTimestamp(fs.statSync(mmdbPath).mtime), "dim");
		} else {
			this.row("Database", "Not installed", "dim");
		}
	}

	storage(): void {
		this.header("Storage");
		this.row("Install path", INSTALL_DIR, "cyan");
		this.row("Browser(s) directory size", dirSize(BROWSERS_DIR), "dim");
		if (allowGeoip()) {
			this.row("GeoIP database size", dirSize(GEOIP_DIR), "dim");
		}
		this.row("Config file", CONFIG_FILE, "cyan");
		this.row("Repo cache", REPO_CACHE_FILE, "cyan");
	}

	async printAll(): Promise<void> {
		await this.packages();
		this.browser();
		this.geoip();
		this.storage();
		// rich's Table.grid(padding=(0, 2)): the first column padded to its
		// widest cell, then two spaces.
		// biome-ignore lint/suspicious/noControlCharactersInRegex: strips ANSI codes to measure
		const visible = (s: string) => s.replace(/\x1b\[[0-9;]*m/g, "").length;
		const width = Math.max(...this.rows.map(([label]) => visible(label)));
		for (const [label, value, st] of this.rows) {
			const pad = " ".repeat(width - visible(label));
			echo(value ? `${label}${pad}  ${style(value, st)}` : label);
		}
	}
}

/** "%Y-%m-%d %H:%M" in local time. */
function localTimestamp(d: Date): string {
	const p = (n: number) => String(n).padStart(2, "0");
	return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function dirSize(dir: string): string {
	if (!fs.existsSync(dir)) return "Nothing here";
	let total = 0;
	const walk = (current: string) => {
		for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
			const full = path.join(current, entry.name);
			if (entry.isDirectory()) walk(full);
			else if (entry.isFile()) total += fs.statSync(full).size;
		}
	};
	walk(dir);
	let size = total;
	for (const unit of ["B", "KB", "MB"]) {
		if (size < 1024) {
			return unit === "B" ? `${size} B` : `${size.toFixed(1)} ${unit}`;
		}
		size /= 1024;
	}
	return `${size.toFixed(1)} GB`;
}

program
	.command("version")
	.description("Display version, package, browser, and storage info")
	.action(async () => {
		await new VersionInfo().printAll();
	});

program
	.command("active")
	.description("Print the current active version")
	.action(() => {
		const config = loadConfig();
		const pinned = config.pinned;
		const channel = config.channel || getDefaultChannel();
		const installed = listInstalled();

		const label = (v: InstalledVersion) => {
			const sha8 = (v.sha256 ?? "").slice(0, 8);
			return sha8 ? `${v.channelPath} (${sha8})` : v.channelPath;
		};

		if (pinned) {
			const pinnedSha = config.pinned_sha;
			const target = pinnedSha
				? (installed.find((v) => v.sha256 === pinnedSha) ?? null)
				: findInstalled(`${channel.toLowerCase()}/${pinned}`);
			if (target) {
				echo(label(target));
			} else {
				echo(`${channel.toLowerCase()}/${pinned} `, false);
				rprint("(not fetched)", "yellow");
			}
			return;
		}

		for (const v of installed) {
			if (v.isActive) {
				echo(label(v));
				return;
			}
		}
		echo(`${channel.toLowerCase()} `, false);
		rprint("(not fetched)", "yellow");
	});

program
	.command("path")
	.description("Print the install directory path")
	.action(() => {
		echo(INSTALL_DIR);
	});

program
	.parseAsync(process.argv)
	.catch((error) => {
		rprint(`Error: ${errorMessage(error)}`, "red");
		process.exitCode = 1;
	})
	.finally(closePrompts);
