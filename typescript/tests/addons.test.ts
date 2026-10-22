/**
 * Mirrors python/tests/test_addons.py: regression guard for #308, where a
 * failed first download left an empty addon directory that was trusted
 * forever afterwards.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

type Addons = typeof import("../src/addons.js");

let tmp: string;
let savedXdg: string | undefined;
let addons: Addons;
let ubo: string;

beforeEach(async () => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-addons-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	// Point the addon store at a throwaway dir so no real cache is touched.
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
	addons = await import("../src/addons.js");
	ubo = addons.getAddonPath("UBO");
	expect(ubo.startsWith(tmp)).toBe(true);
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	fs.rmSync(tmp, { recursive: true, force: true });
});

function writeManifest(extractPath: string) {
	fs.mkdirSync(extractPath, { recursive: true });
	fs.writeFileSync(path.join(extractPath, "manifest.json"), "{}");
}

it("re-downloads a partial (manifest-less) directory", async () => {
	fs.mkdirSync(ubo, { recursive: true });
	const calls: string[] = [];
	addons.addonsDeps.downloadAndExtract = async (_url, extractPath, name) => {
		calls.push(name);
		writeManifest(extractPath);
	};

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);

	expect(calls).toEqual(["UBO"]);
	expect(fs.existsSync(path.join(ubo, "manifest.json"))).toBe(true);
	expect(out).toEqual([ubo]);
});

it("does not re-download an extracted addon", async () => {
	writeManifest(ubo);
	addons.addonsDeps.downloadAndExtract = async () => {
		throw new Error("must not re-download an already-extracted addon");
	};

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);
	expect(out).toEqual([ubo]);
});

it("removes the partial directory when a download fails", async () => {
	addons.addonsDeps.downloadAndExtract = async (_url, extractPath) => {
		fs.mkdirSync(extractPath, { recursive: true }); // partial write, then die
		throw new Error("network died mid-download");
	};
	const log = vi.spyOn(console, "log").mockImplementation(() => {});

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);

	expect(fs.existsSync(ubo)).toBe(false);
	expect(out).toEqual([]);
	expect(log).toHaveBeenCalledWith(
		"Failed to download and extract UBO: Error: network died mid-download",
	);
	log.mockRestore();
});

it("downloads once for concurrent launches", async () => {
	// Two launches in one process share the check-then-extract; unserialized,
	// both saw no manifest at the await and both downloaded.
	const calls: string[] = [];
	addons.addonsDeps.downloadAndExtract = async (_url, extractPath, name) => {
		calls.push(name);
		await new Promise((resolve) => setTimeout(resolve, 50));
		writeManifest(extractPath);
	};

	const outs: string[][] = [[], []];
	await Promise.all(outs.map((out) => addons.addDefaultAddons(out)));

	expect(calls).toEqual(["UBO"]);
	expect(outs).toEqual([[ubo], [ubo]]);
});

/** Re-imports addons with webdl stubbed and unzip replaced by `fakeUnzip`. */
async function withUnzip(fakeUnzip: (extractPath: string) => void) {
	vi.resetModules();
	vi.doMock("../src/pkgman.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("../src/pkgman.js")>()),
		webdl: async () => Buffer.alloc(0),
		unzip: (_buffer: Buffer, extractPath: string) => fakeUnzip(extractPath),
	}));
	const mod: Addons = await import("../src/addons.js");
	vi.doUnmock("../src/pkgman.js");
	return mod;
}

it("extracts so the addon appears complete or not at all", async () => {
	// Another process checks for manifest.json without the chain, so the addon
	// directory must never hold a manifest while its other files are missing.
	fs.mkdirSync(ubo, { recursive: true });
	const seen: boolean[] = [];
	const mod = await withUnzip((extractPath) => {
		seen.push(fs.existsSync(path.join(ubo, "manifest.json")));
		writeManifest(extractPath);
		fs.writeFileSync(path.join(extractPath, "background.js"), "");
		seen.push(fs.existsSync(path.join(ubo, "manifest.json")));
	});

	await mod.downloadAndExtract("url", ubo, "UBO");

	expect(seen).toEqual([false, false]);
	expect(fs.readdirSync(ubo).sort()).toEqual([
		"background.js",
		"manifest.json",
	]);
	expect(fs.readdirSync(path.dirname(ubo))).toEqual(["UBO"]);
});

it("keeps a complete addon installed meanwhile", async () => {
	// Another process can finish installing the addon while this one extracts.
	// Its copy may already be loading in a browser, so it must not be deleted.
	fs.mkdirSync(ubo, { recursive: true });
	const mod = await withUnzip((extractPath) => {
		writeManifest(extractPath);
		writeManifest(ubo);
		fs.writeFileSync(path.join(ubo, "theirs.js"), "");
	});

	await mod.downloadAndExtract("url", ubo, "UBO");

	expect(fs.readdirSync(ubo).sort()).toEqual(["manifest.json", "theirs.js"]);
	expect(fs.readdirSync(path.dirname(ubo))).toEqual(["UBO"]);
});

it("keeps a complete addon when a download fails", async () => {
	// This launch's download fails after another process installed the addon.
	// That copy may already be loading in a browser, so it must not be deleted.
	addons.addonsDeps.downloadAndExtract = async () => {
		writeManifest(ubo);
		throw new Error("network died mid-download");
	};
	const log = vi.spyOn(console, "log").mockImplementation(() => {});

	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);

	expect(fs.existsSync(path.join(ubo, "manifest.json"))).toBe(true);
	expect(out).toEqual([]);
	log.mockRestore();
});
