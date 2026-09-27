/**
 * Mirrors pythonlib/tests/test_profile_directory.py (the pkgman half; the
 * launch-preflight ordering is covered with the launcher tests): Firefox
 * probes ~/.camoufox at startup even with a Playwright-supplied profile.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let tmp: string;
let home: string;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-profile-"));
	home = path.join(tmp, "home");
	vi.resetModules();
});

afterEach(() => {
	vi.doUnmock("../src/paths.js");
	vi.doUnmock("../src/multiversion.js");
	for (const p of [path.join(home, ".camoufox"), home]) {
		try {
			fs.chmodSync(p, 0o700);
		} catch {}
	}
	fs.rmSync(tmp, { recursive: true, force: true });
});

async function pkgmanAs(osName: "lin" | "mac" | "win") {
	vi.doMock("../src/paths.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("../src/paths.js")>()),
		OS_NAME: osName,
	}));
	return import("../src/pkgman.js");
}

it("creates a missing Linux profile directory", async () => {
	fs.mkdirSync(home);
	const pkgman = await pkgmanAs("lin");

	const profileDir = pkgman.ensureBrowserProfileDir({ HOME: home });

	expect(profileDir).toBe(path.join(home, ".camoufox"));
	expect(fs.statSync(profileDir as string).isDirectory()).toBe(true);
});

it("accepts an existing profile directory that is read-only", async () => {
	const profileDir = path.join(home, ".camoufox");
	fs.mkdirSync(profileDir, { recursive: true });
	const pkgman = await pkgmanAs("lin");
	fs.chmodSync(home, 0o500);
	fs.chmodSync(profileDir, 0o500);

	expect(pkgman.ensureBrowserProfileDir({ HOME: home })).toBe(profileDir);
});

it.skipIf(process.platform === "win32" || process.getuid?.() === 0)(
	"fails fast when the profile directory cannot be created",
	async () => {
		fs.mkdirSync(home);
		const pkgman = await pkgmanAs("lin");
		const { ProfileDirectoryError } = await import("../src/exceptions.js");
		fs.chmodSync(home, 0o500);

		expect(() => pkgman.ensureBrowserProfileDir({ HOME: home })).toThrow(
			ProfileDirectoryError,
		);
		expect(() => pkgman.ensureBrowserProfileDir({ HOME: home })).toThrow(
			/\.camoufox.*before.*read-only/,
		);
	},
);

it("does not create the Linux directory on other platforms", async () => {
	fs.mkdirSync(home);
	const pkgman = await pkgmanAs("mac");

	expect(pkgman.ensureBrowserProfileDir({ HOME: home })).toBeUndefined();
	expect(fs.existsSync(path.join(home, ".camoufox"))).toBe(false);
});

it("falls back to the process HOME when the env mapping has none", async () => {
	fs.mkdirSync(home);
	const saved = process.env.HOME;
	process.env.HOME = home;
	try {
		const pkgman = await pkgmanAs("lin");
		expect(pkgman.ensureBrowserProfileDir({})).toBe(
			path.join(home, ".camoufox"),
		);
	} finally {
		process.env.HOME = saved;
	}
});

it("fetch prepares the profile directory", async () => {
	fs.mkdirSync(home);
	const saved = process.env.HOME;
	process.env.HOME = home;
	try {
		vi.doMock("../src/multiversion.js", async (importOriginal) => ({
			...(await importOriginal<typeof import("../src/multiversion.js")>()),
			installVersioned: async () => true,
		}));
		const pkgman = await pkgmanAs("lin");
		const fetcher = Object.create(
			pkgman.CamoufoxFetcher.prototype,
		) as InstanceType<typeof pkgman.CamoufoxFetcher>;

		await fetcher.install();

		expect(fs.statSync(path.join(home, ".camoufox")).isDirectory()).toBe(true);
	} finally {
		process.env.HOME = saved;
	}
});
