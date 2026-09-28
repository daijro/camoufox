/**
 * Mirrors pythonlib/tests/test_browser_pin.py: a released library runs the
 * browser it was released with, and nothing else by default.
 *
 * INSTALL_DIR is computed at import from XDG_CACHE_HOME, so every test points
 * that at a fresh directory and re-imports the modules.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const PIN = {
	tag: "v156.0.1-beta.33",
	repo: "daijro/camoufox",
	repo_name: "Official",
	version: "156.0.1",
	build: "beta.33",
};

let tmp: string;
let savedXdg: string | undefined;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-pin-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	fs.rmSync(tmp, { recursive: true, force: true });
	vi.restoreAllMocks();
});

async function setup(opts: {
	pin: object;
	installed: string[];
	config: Record<string, string>;
}) {
	const pinMod = await import("../src/browser-pin.js");
	const pkgman = await import("../src/pkgman.js");
	const multiversion = await import("../src/multiversion.js");
	const exc = await import("../src/exceptions.js");
	const root = pkgman.INSTALL_DIR;
	fs.mkdirSync(root, { recursive: true });
	fs.writeFileSync(path.join(root, ".0.5_FLAG"), "");
	fs.writeFileSync(path.join(root, "repo_cache.json"), "{}");
	fs.writeFileSync(path.join(root, "config.json"), JSON.stringify(opts.config));
	for (const spec of opts.installed) {
		const dash = spec.indexOf("-");
		const dir = path.join(root, "browsers", "official", spec);
		fs.mkdirSync(dir, { recursive: true });
		fs.writeFileSync(
			path.join(dir, "version.json"),
			JSON.stringify({
				version: spec.slice(0, dash),
				build: spec.slice(dash + 1),
			}),
		);
	}
	const pinFile = path.join(tmp, "browser-pin.json");
	fs.writeFileSync(pinFile, JSON.stringify(opts.pin));
	pinMod.browserPinDeps.file = pinFile;
	pinMod.resetUnpairedWarning();
	return { pinMod, pkgman, multiversion, exc, root };
}

describe("the pin file", () => {
	it.each([
		"{}",
		'{"tag": null}',
		"",
		"not json",
	])("an empty or unreadable pin (%j) pins nothing", async (content) => {
		const { loadPin } = await import("../src/browser-pin.js");
		const f = path.join(tmp, "p.json");
		fs.writeFileSync(f, content);
		expect(loadPin(f)).toBeNull();
		expect(loadPin(path.join(tmp, "absent.json"))).toBeNull();
	});

	it("the checked-in pin is empty: only the release workflow writes one", () => {
		const file = path.resolve(
			__dirname,
			"../../pythonlib/camoufox/browser-pin.json",
		);
		expect(JSON.parse(fs.readFileSync(file, "utf-8"))).toEqual({});
	});
});

describe("launch", () => {
	it("uses the paired build even when another is marked active", async () => {
		const { pkgman, multiversion, root } = await setup({
			pin: PIN,
			installed: ["156.0.1-beta.33", "157.0-beta.34"],
			config: { active_version: "browsers/official/157.0-beta.34" },
		});
		expect(multiversion.getActivePath()).toBe(
			path.join(root, "browsers/official/156.0.1-beta.33"),
		);
		expect(pkgman.installedVerStr()).toBe("156.0.1-beta.33");
	});

	it("does not fall back to a newer build when the paired one is missing", async () => {
		const { pkgman, multiversion, exc } = await setup({
			pin: PIN,
			installed: ["157.0-beta.34"],
			config: {},
		});
		expect(multiversion.getActivePath()).toBeNull();
		expect(() => pkgman.installedVerStr()).toThrow(exc.CamoufoxNotInstalled);
		expect(() => pkgman.installedVerStr()).toThrow(/156\.0\.1-beta\.33/);
	});

	it("reports a missing paired build as not installed, not outdated", async () => {
		const { pkgman, exc } = await setup({
			pin: PIN,
			installed: ["157.0-beta.34"],
			config: {},
		});
		expect(() => pkgman.camoufoxPath()).toThrow(exc.CamoufoxNotInstalled);
		expect(() => pkgman.camoufoxPath()).toThrow(/pairs with/);
	});

	it("keeps an explicit choice and warns about it once", async () => {
		const { pkgman, multiversion, root } = await setup({
			pin: PIN,
			installed: ["156.0.1-beta.33", "157.0-beta.34"],
			config: {
				channel: "official/stable",
				active_version: "browsers/official/157.0-beta.34",
			},
		});
		const emit = vi.spyOn(process, "emitWarning").mockImplementation(() => {});
		expect(multiversion.getActivePath()).toBe(
			path.join(root, "browsers/official/157.0-beta.34"),
		);
		expect(pkgman.installedVerStr()).toBe("157.0-beta.34");
		pkgman.installedVerStr();
		expect(emit).toHaveBeenCalledTimes(1);
		expect(String(emit.mock.calls[0][0])).toContain("v156.0.1-beta.33");
	});

	it("does not warn when the explicit choice is the paired build", async () => {
		const { pkgman } = await setup({
			pin: PIN,
			installed: ["156.0.1-beta.33"],
			config: {
				pinned: "156.0.1-beta.33",
				channel: "official/prerelease",
				active_version: "browsers/official/156.0.1-beta.33",
			},
		});
		const emit = vi.spyOn(process, "emitWarning").mockImplementation(() => {});
		expect(pkgman.installedVerStr()).toBe("156.0.1-beta.33");
		expect(emit).not.toHaveBeenCalled();
	});

	it("leaves the channel logic unchanged without a pin", async () => {
		const { multiversion, root } = await setup({
			pin: {},
			installed: ["156.0.1-beta.33", "157.0-beta.34"],
			config: { active_version: "browsers/official/157.0-beta.34" },
		});
		expect(multiversion.getActivePath()).toBe(
			path.join(root, "browsers/official/157.0-beta.34"),
		);
	});
});

describe("the fetcher", () => {
	it.each([
		[{}, false],
		[{ channel: "official/stable" }, true],
	])("with config %j accepts only the paired asset unless chosen otherwise", async (config, acceptsNewer) => {
		const { pkgman } = await setup({ pin: PIN, installed: [], config });
		const fetcher = Object.create(pkgman.CamoufoxFetcher.prototype);
		fetcher.repoConfig = pkgman.RepoConfig.getDefault();
		fetcher.pattern = fetcher.repoConfig.buildPattern("lin", "x86_64");
		const asset = (version: string, build: string) => ({
			name: `camoufox-${version}-${build}-lin.x86_64.zip`,
			browser_download_url: `https://example.invalid/${version}-${build}.zip`,
		});
		expect(
			fetcher.checkAsset(asset("156.0.1", "beta.33"), { prerelease: true }),
		).not.toBeNull();
		const newer = fetcher.checkAsset(asset("157.0", "beta.34"), {
			prerelease: false,
		});
		expect(newer !== null).toBe(acceptsNewer);
	});
});
