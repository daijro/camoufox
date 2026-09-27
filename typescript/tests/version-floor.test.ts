/**
 * Mirrors pythonlib/tests/test_version_floor_upgrade.py: raising the browser
 * floor must upgrade a below-floor install, in both install layouts, and the
 * floor is keyed on the resolved Playwright.
 *
 * INSTALL_DIR is computed at import from XDG_CACHE_HOME, so every test points
 * that at a fresh directory and re-imports the modules.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Pkgman = typeof import("../src/pkgman.js");
type Exceptions = typeof import("../src/exceptions.js");

let tmp: string;
let savedXdg: string | undefined;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-floor-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	fs.rmSync(tmp, { recursive: true, force: true });
});

async function load(): Promise<{ pkgman: Pkgman; exc: Exceptions }> {
	const pkgman = await import("../src/pkgman.js");
	const exc = await import("../src/exceptions.js");
	return { pkgman, exc };
}

/** Build an install dir in the given layout and point the library at it. */
async function install(
	layout: "versioned" | "legacy",
	build: string,
	floor: string,
) {
	const { pkgman, exc } = await load();
	const root = pkgman.INSTALL_DIR;
	fs.mkdirSync(root, { recursive: true });
	fs.writeFileSync(path.join(root, ".0.5_FLAG"), "");
	fs.writeFileSync(path.join(root, "repo_cache.json"), "{}");

	let versionDir: string;
	if (layout === "versioned") {
		const relative = `browsers/official/152.0.4-${build}`;
		fs.writeFileSync(
			path.join(root, "config.json"),
			JSON.stringify({ active_version: relative }),
		);
		versionDir = path.join(root, relative);
		fs.mkdirSync(versionDir, { recursive: true });
	} else {
		fs.writeFileSync(path.join(root, "config.json"), "{}");
		versionDir = root;
	}
	fs.writeFileSync(
		path.join(versionDir, "version.json"),
		JSON.stringify({ version: "152.0.4", build }),
	);
	pkgman.pkgmanDeps.versionMin = () => new pkgman.Version(floor);
	// The floor under test is VERSION_MIN alone unless a test says otherwise.
	pkgman.pkgmanDeps.resolvedPlaywrightVersion = () => null;
	return { pkgman, exc, root };
}

for (const layout of ["versioned", "legacy"] as const) {
	it(`reports a below-floor ${layout} install as outdated, never as missing`, async () => {
		const { pkgman, exc } = await install(layout, "beta.29", "beta.30");
		expect(() => pkgman.camoufoxPath()).toThrow(exc.UnsupportedVersion);
	});

	it(`keeps an at-floor ${layout} install`, async () => {
		const { pkgman, root } = await install(layout, "beta.30", "beta.30");
		const expected =
			layout === "legacy"
				? root
				: path.join(root, "browsers/official/152.0.4-beta.30");
		expect(pkgman.camoufoxPath()).toBe(expected);
	});
}

it("upgrades a below-floor install instead of raising", async () => {
	const { pkgman, root } = await install("versioned", "beta.29", "beta.30");
	const installed: boolean[] = [];
	pkgman.pkgmanDeps.newFetcher = async () => ({
		async install() {
			installed.push(true);
			const relative = "browsers/official/152.0.4-beta.30";
			const versionDir = path.join(root, relative);
			fs.mkdirSync(versionDir, { recursive: true });
			fs.writeFileSync(
				path.join(versionDir, "version.json"),
				JSON.stringify({ version: "152.0.4", build: "beta.30" }),
			);
			fs.writeFileSync(
				path.join(root, "config.json"),
				JSON.stringify({ active_version: relative }),
			);
		},
	});

	const resolved = await pkgman.ensureCamoufoxInstalled();

	expect(installed).toEqual([true]);
	expect(resolved).toBe(path.join(root, "browsers/official/152.0.4-beta.30"));
});

it("the root probe reports false, rather than raising, with no root file", async () => {
	const { pkgman } = await load();
	fs.mkdirSync(pkgman.INSTALL_DIR, { recursive: true });
	expect(pkgman.rootInstallSupported()).toBe(false);
});

it("an unsatisfiable floor reports instead of recursing", async () => {
	const { pkgman, exc } = await install("versioned", "beta.29", "beta.30");
	const attempts: boolean[] = [];
	pkgman.pkgmanDeps.newFetcher = async () => ({
		async install() {
			attempts.push(true); // newest published build is still below the floor
		},
	});

	await expect(pkgman.ensureCamoufoxInstalled()).rejects.toBeInstanceOf(
		exc.UnsupportedVersion,
	);
	expect(attempts).toEqual([true]);
});

describe("conditional floor", () => {
	async function withPlaywright(version: string | null) {
		const { pkgman } = await load();
		pkgman.pkgmanDeps.resolvedPlaywrightVersion = () =>
			version === null ? null : version.split(".").map(Number);
		return pkgman;
	}

	for (const version of ["1.53.0", "1.60.0"]) {
		it(`leaves older builds alone on Playwright ${version}`, async () => {
			const pkgman = await withPlaywright(version);
			expect(pkgman.effectiveVersionMin().build).toBe("alpha.1");
		});
	}

	for (const version of ["1.61.0", "1.62.0"]) {
		it(`raises the floor on Playwright ${version}`, async () => {
			const pkgman = await withPlaywright(version);
			expect(pkgman.effectiveVersionMin().build).toBe("beta.30");
		});
	}

	it("falls back permissive when Playwright cannot be read", async () => {
		const pkgman = await withPlaywright(null);
		expect(pkgman.effectiveVersionMin().build).toBe("alpha.1");
	});

	it("reads the resolved playwright-core", async () => {
		const { pkgman } = await load();
		const version = pkgman.resolvedPlaywrightVersion();
		expect(version).not.toBeNull();
		expect(pkgman.resolvedPlaywrightVersionStr()).toBe(version?.join("."));
	});

	it("keeps a below-floor install on old Playwright", async () => {
		const { pkgman } = await install("versioned", "beta.29", "alpha.1");
		pkgman.pkgmanDeps.resolvedPlaywrightVersion = () => [1, 60, 0];
		expect(path.basename(pkgman.camoufoxPath())).toBe("152.0.4-beta.29");
	});

	it("moves a below-floor install on new Playwright", async () => {
		const { pkgman, exc } = await install("versioned", "beta.29", "alpha.1");
		pkgman.pkgmanDeps.resolvedPlaywrightVersion = () => [1, 62, 0];
		expect(() => pkgman.camoufoxPath()).toThrow(exc.UnsupportedVersion);
	});
});
