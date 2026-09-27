/**
 * multiversion.ts against pythonlib/camoufox/multiversion.py: ordering is
 * Python's (code-point string comparison, not locale collation), the install
 * scan and specifier lookup, and removal bookkeeping.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type MV = typeof import("../src/multiversion.js");

let tmp: string;
let savedXdg: string | undefined;
let mv: MV;

beforeEach(async () => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-mv-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
	mv = await import("../src/multiversion.js");
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	fs.rmSync(tmp, { recursive: true, force: true });
});

function addInstall(repo: string, folder: string, data: object) {
	const dir = path.join(mv.BROWSERS_DIR, repo, folder);
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(path.join(dir, "version.json"), JSON.stringify(data));
	return dir;
}

it("latestPerBuild keeps the newest asset per build, sorted like Python", () => {
	const v = (version: string, build: string, created_at: string) =>
		({ version, build, url: "", created_at }) as any;
	const out = mv.latestPerBuild([
		v("152.0.4", "beta.9", "2026-01-01"),
		v("152.0.4", "beta.9", "2026-02-01"),
		v("152.0.4", "beta.30", "2026-03-01"),
		// Upper case sorts before lower case by code point; localeCompare would
		// interleave them.
		v("B", "x", "2026-01-01"),
		v("a", "x", "2026-01-01"),
	]);
	expect(out.map((x) => `${x.version}-${x.build}@${x.created_at}`)).toEqual([
		"a-x@2026-01-01",
		"B-x@2026-01-01",
		// Same version string: the tie falls to created_at, newest first.
		"152.0.4-beta.30@2026-03-01",
		"152.0.4-beta.9@2026-02-01",
	]);
});

it("lists installs by repo then version, descending, and finds them", () => {
	addInstall("official", "152.0.4-beta.29", {
		version: "152.0.4",
		build: "beta.29",
	});
	addInstall("official", "152.0.4-beta.30-3a7958c8", {
		version: "152.0.4",
		build: "beta.30",
		sha256: "3a7958c8ffff",
		prerelease: false,
	});
	addInstall("Zed", "1.0-alpha.1", { version: "1.0", build: "alpha.1" });
	fs.mkdirSync(path.join(mv.BROWSERS_DIR, ".hidden", "x"), { recursive: true });

	const installed = mv.listInstalled();
	expect(installed.map((v) => v.relativePath)).toEqual([
		"browsers/official/152.0.4-beta.30-3a7958c8",
		"browsers/official/152.0.4-beta.29",
		"browsers/Zed/1.0-alpha.1",
	]);
	expect(installed[0].channelPath).toBe("official/stable/152.0.4-beta.30");

	expect(mv.findInstalledVersion("beta.29")).toBe(installed[1].path);
	expect(mv.findInstalledVersion("official/beta.30")).toBe(installed[0].path);
	expect(mv.findInstalledVersion("152.0.4-beta.30")).toBe(installed[0].path);
	expect(mv.findInstalledVersion("nope")).toBeNull();
});

it("auto-selects the first install when no channel or pin is set", () => {
	const dir = addInstall("official", "152.0.4-beta.30", {
		version: "152.0.4",
		build: "beta.30",
	});
	expect(mv.getActivePath()).toBe(dir);
	expect(mv.loadConfig().active_version).toBe(
		"browsers/official/152.0.4-beta.30",
	);
	// With a channel set, nothing is auto-selected.
	mv.saveConfig({ channel: "official/stable" });
	expect(mv.getActivePath()).toBeNull();
});

it("writes config.json as orjson OPT_INDENT_2 does", () => {
	mv.saveConfig({ channel: "official/stable", pinned: "x" });
	expect(fs.readFileSync(mv.CONFIG_FILE, "utf-8")).toBe(
		'{\n  "channel": "official/stable",\n  "pinned": "x"\n}',
	);
});

it("removeVersion prunes empty parents and re-points the active version", () => {
	const a = addInstall("official", "152.0.4-beta.30", {
		version: "152.0.4",
		build: "beta.30",
	});
	const b = addInstall("other", "1.0-beta.1", {
		version: "1.0",
		build: "beta.1",
	});
	mv.setActive("browsers/other/1.0-beta.1");
	vi.spyOn(process.stdout, "write").mockImplementation(() => true);

	expect(mv.removeVersion(b)).toBe(true);
	expect(fs.existsSync(path.dirname(b))).toBe(false);
	expect(mv.loadConfig().active_version).toBe(
		"browsers/official/152.0.4-beta.30",
	);

	expect(mv.removeVersion(a)).toBe(true);
	expect(fs.existsSync(mv.BROWSERS_DIR)).toBe(false);
	expect(mv.loadConfig().active_version).toBeNull();
	expect(mv.removeVersion(a)).toBe(false);
	vi.restoreAllMocks();
});

it("classifies catalog items against installs, legacy folders included", async () => {
	const { AvailableVersion, Version } = await import("../src/pkgman.js");
	addInstall("official", "152.0.4-beta.30-aaaaaaaa", {
		version: "152.0.4",
		build: "beta.30",
		sha256: "aaaaaaaa11",
	});
	addInstall("official", "152.0.4-beta.29", {
		version: "152.0.4",
		build: "beta.29",
	});
	const av = (build: string, sha?: string) =>
		new AvailableVersion({
			version: new Version(build, "152.0.4"),
			url: "",
			isPrerelease: false,
			sha256: sha,
		});
	const [rows, extras] = mv.classifyInstalls(
		[av("beta.30", "aaaaaaaa11"), av("beta.30", "bbbbbbbb22"), av("beta.29")],
		mv.listInstalled(),
	);
	expect(rows.map((r) => r?.folderName ?? null)).toEqual([
		"152.0.4-beta.30-aaaaaaaa",
		null,
		"152.0.4-beta.29",
	]);
	expect(extras).toEqual([]);
});
