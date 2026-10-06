/**
 * Mirrors pythonlib/tests/test_browser_interface.py: a browser declares the
 * interface it speaks, and the library refuses one it cannot drive (#835).
 *
 * INSTALL_DIR is computed at import from XDG_CACHE_HOME, so every test points
 * that at a fresh directory and re-imports the modules.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONSTRAINTS } from "../src/__version__.js";

const NEWER = CONSTRAINTS.INTERFACE + 1;

let tmp: string;
let savedXdg: string | undefined;
let served: Map<string, unknown>;
let fetched: string[];

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-iface-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
	served = new Map();
	fetched = [];
	vi.stubGlobal("fetch", async (url: string) => {
		fetched.push(url);
		return new Response(JSON.stringify(served.get(url)));
	});
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	fs.rmSync(tmp, { recursive: true, force: true });
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

function release(tag: string, build: string, manifest?: object) {
	const assets: Array<Record<string, unknown>> = [
		{
			name: `camoufox-156.0.1-${build}-lin.x86_64.zip`,
			browser_download_url: `https://example.invalid/${tag}/browser.zip`,
		},
	];
	if (manifest) {
		const url = `https://example.invalid/${tag}/manifest.json`;
		served.set(url, manifest);
		assets.push({ name: "manifest.json", id: tag, browser_download_url: url });
	}
	return { tag_name: tag, prerelease: false, assets } as any;
}

describe("a release's interface", () => {
	it("is 1 without a manifest, and nothing is fetched", async () => {
		const pkgman = await import("../src/pkgman.js");
		expect(
			await pkgman.releaseInterface(release("v156.0.1-beta.31", "beta.31")),
		).toBe(1);
		expect(fetched).toEqual([]);
	});

	it("is 1 when the manifest predates the field", async () => {
		const pkgman = await import("../src/pkgman.js");
		expect(
			await pkgman.releaseInterface(
				release("v156.0.1-beta.33", "beta.33", { schema: 1 }),
			),
		).toBe(1);
	});
});

describe("choosing a browser", () => {
	it("skips a browser this library cannot drive", async () => {
		const pkgman = await import("../src/pkgman.js");
		const pin = await import("../src/browser-pin.js");
		vi.spyOn(pin, "effectivePin").mockReturnValue(null);
		const fetcher = Object.create(pkgman.CamoufoxFetcher.prototype);
		fetcher.repoConfig = pkgman.RepoConfig.getDefault();
		fetcher.pattern = fetcher.repoConfig.buildPattern("lin", "x86_64");
		fetcher.githubRepos = ["daijro/camoufox"];
		fetcher.getReleases = async () => [
			release("v156.0.1-beta.40", "beta.40", { interface: NEWER }),
			release("v156.0.1-beta.39", "beta.39", {
				interface: CONSTRAINTS.INTERFACE,
			}),
		];
		const [version] = await fetcher.getAsset();
		expect(version.build).toBe("beta.39");
		expect(fetcher.installedInterface).toBe(CONSTRAINTS.INTERFACE);
	});

	it("lists only browsers this library can drive", async () => {
		const pkgman = await import("../src/pkgman.js");
		served.set("https://api.github.com/repos/daijro/camoufox/releases", [
			release("v156.0.1-beta.40", "beta.40", { interface: NEWER }),
			release("v156.0.1-beta.39", "beta.39", {
				interface: CONSTRAINTS.INTERFACE,
			}),
			release("v156.0.1-beta.31", "beta.31"),
		]);
		const versions = await pkgman.listAvailableVersions(
			undefined,
			true,
			"lin",
			"x86_64",
		);
		expect(versions.map((v) => v.version.build)).toEqual([
			"beta.39",
			"beta.31",
		]);
		expect(versions.map((v) => v.interface)).toEqual([
			CONSTRAINTS.INTERFACE,
			1,
		]);
	});
});

describe("launching", () => {
	async function activeInstall(iface?: number) {
		const pkgman = await import("../src/pkgman.js");
		const pin = await import("../src/browser-pin.js");
		vi.spyOn(pin, "effectivePin").mockReturnValue(null);
		const root = pkgman.INSTALL_DIR;
		const relative = "browsers/official/156.0.1-beta.40";
		const dir = path.join(root, relative);
		fs.mkdirSync(dir, { recursive: true });
		fs.writeFileSync(path.join(root, ".0.5_FLAG"), "");
		fs.writeFileSync(
			path.join(root, "config.json"),
			JSON.stringify({ active_version: relative }),
		);
		const metadata: Record<string, unknown> = {
			version: "156.0.1",
			build: "beta.40",
		};
		if (iface !== undefined) metadata.interface = iface;
		fs.writeFileSync(path.join(dir, "version.json"), JSON.stringify(metadata));
		return { pkgman, dir };
	}

	it("refuses an installed browser this library cannot drive", async () => {
		const { pkgman } = await activeInstall(NEWER);
		expect(() => pkgman.camoufoxPath()).toThrow(
			/npm install camoufox@latest/,
		);
	});

	it.each([
		[undefined],
		[CONSTRAINTS.INTERFACE],
	])("keeps a browser it can drive (version.json interface %j)", async (iface) => {
		const { pkgman, dir } = await activeInstall(iface);
		expect(pkgman.camoufoxPath()).toBe(dir);
	});
});

describe("upgrade warning", () => {
	async function synced(incompatible: object[]) {
		const pkgman = await import("../src/pkgman.js");
		const root = pkgman.INSTALL_DIR;
		fs.mkdirSync(root, { recursive: true });
		fs.writeFileSync(
			path.join(root, "repo_cache.json"),
			JSON.stringify({ repos: [], incompatible }),
		);
		pkgman.resetOutdatedWarning();
		const warnings = await import("../src/warnings.js");
		const seen: string[] = [];
		vi.spyOn(process, "emitWarning").mockImplementation(((msg: unknown) => {
			seen.push(String(msg));
		}) as typeof process.emitWarning);
		return { pkgman, warnings, seen };
	}

	it("warns once when sync found a browser that needs an upgrade", async () => {
		const { pkgman, seen } = await synced([
			{
				repo: "Official",
				version: "156.0.1",
				build: "beta.40",
				interface: NEWER,
			},
			{
				repo: "Official",
				version: "156.0.1",
				build: "beta.41",
				interface: NEWER,
			},
		]);
		pkgman.warnIfPackageOutdated();
		pkgman.warnIfPackageOutdated();
		expect(seen).toHaveLength(1);
		expect(seen[0]).toMatch(
			/v156\.0\.1-beta\.41 needs a newer camoufox package.*npm install camoufox@latest/,
		);
	});

	it("is silent when every synced browser is drivable", async () => {
		const { pkgman, seen } = await synced([]);
		pkgman.warnIfPackageOutdated();
		expect(seen).toEqual([]);
	});
});
