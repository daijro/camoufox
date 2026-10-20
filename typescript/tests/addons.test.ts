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

it("raises and removes the partial directory when a download fails", async () => {
	addons.addonsDeps.downloadAndExtract = async (_url, extractPath) => {
		fs.mkdirSync(extractPath, { recursive: true }); // partial write, then die
		throw new Error("network died mid-download");
	};

	// Launching without the addon would be a different browser than asked for.
	await expect(
		addons.maybeDownloadAddons({ ...addons.DefaultAddons }, []),
	).rejects.toThrow("network died mid-download");
	expect(fs.existsSync(ubo)).toBe(false);
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
		verifySha256: () => {},
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
	expect(fs.readdirSync(path.dirname(ubo))).toEqual([path.basename(ubo)]);
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
	expect(fs.readdirSync(path.dirname(ubo))).toEqual([path.basename(ubo)]);
});

it("keeps a complete addon when a download fails", async () => {
	// This launch's download fails after another process installed the addon.
	// That copy may already be loading in a browser, so it must not be deleted.
	addons.addonsDeps.downloadAndExtract = async () => {
		writeManifest(ubo);
		throw new Error("network died mid-download");
	};
	const out: string[] = [];
	await addons.maybeDownloadAddons({ ...addons.DefaultAddons }, out);

	expect(fs.existsSync(path.join(ubo, "manifest.json"))).toBe(true);
	expect(out).toEqual([ubo]);
});

const PINS = JSON.parse(
	fs.readFileSync(
		path.join(import.meta.dirname, "../../python/src/camoufox/addons.json"),
		"utf-8",
	),
);

it("pins every default addon to one file", () => {
	for (const [name, url] of Object.entries(addons.DefaultAddons)) {
		const pin = PINS[name];
		expect(url).toBe(pin.url);
		expect(pin.url).toContain(`-${pin.version}.xpi`);
		expect(pin.sha256).toMatch(/^[0-9a-f]{64}$/);
	}
});

it("caches each pinned version in its own directory", () => {
	// A cache filled by another release must not stand in for this one's pin.
	expect(ubo).toBe(
		path.join(tmp, "camoufox", "addons", "UBO", PINS.UBO.version),
	);
});

it("rejects a download that does not match the pin", async () => {
	vi.doMock("../src/pkgman.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("../src/pkgman.js")>()),
		webdl: async () => Buffer.from("not the pinned xpi"),
	}));
	vi.resetModules();
	const mocked: Addons = await import("../src/addons.js");
	const { CorruptedDownload } = await import("../src/exceptions.js");

	try {
		await expect(
			mocked.maybeDownloadAddons({ ...mocked.DefaultAddons }, []),
		).rejects.toBeInstanceOf(CorruptedDownload);
		const dir = path.dirname(ubo);
		expect(fs.existsSync(dir) ? fs.readdirSync(dir) : []).toEqual([]);
	} finally {
		vi.doUnmock("../src/pkgman.js");
	}
});
