/**
 * Mirrors pythonlib/tests/test_geoip_config.py: which GeoIP source is active,
 * and when its database is refreshed.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { stringify as stringifyYaml } from "yaml";

const DEFAULT = "GeoIP AIO by daijro";
const DEPRECATED = "MaxMind GeoLite2";
const DAY_MS = 24 * 60 * 60 * 1000;

let tmp: string;
let g: typeof import("../src/geolocation.js");
let w: typeof import("../src/warnings.js");

beforeEach(async () => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-geoip-"));
	vi.resetModules();
	// INSTALL_DIR is computed at import time
	vi.doMock("../src/paths.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("../src/paths.js")>()),
		INSTALL_DIR: tmp,
	}));
	g = await import("../src/geolocation.js");
	w = await import("../src/warnings.js");
});

afterEach(() => {
	vi.doUnmock("../src/paths.js");
	fs.rmSync(tmp, { recursive: true, force: true });
});

function saved(fields: Record<string, unknown>) {
	fs.mkdirSync(g.GEOIP_DIR, { recursive: true });
	fs.writeFileSync(g.GEOIP_CONFIG, stringifyYaml(fields));
}

it("defaults to AIO", () => {
	expect(g.loadGeoipConfig().name).toBe(DEFAULT);
});

it("moves an implicit deprecated source to the default", () => {
	// What every cache written before the default changed holds
	saved({ name: DEPRECATED });
	expect(g.loadGeoipConfig().name).toBe(DEFAULT);
});

it("keeps an explicit deprecated source", () => {
	saved({ name: DEPRECATED, explicit: true });
	expect(g.loadGeoipConfig().name).toBe(DEPRECATED);
});

it("records an explicit choice", () => {
	const config = g.getGeoipConfigByName(DEPRECATED);
	g.saveGeoipConfig(config, true);
	expect(g.loadGeoipConfig().name).toBe(DEPRECATED);
	g.saveGeoipConfig(config);
	expect(g.loadGeoipConfig().name).toBe(DEFAULT);
});

it("keeps an explicit choice through a refresh", async () => {
	// `camoufox fetch` and the weekly refresh download without naming a source
	saved({ name: DEPRECATED, explicit: true });
	vi.doMock("../src/pkgman.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("../src/pkgman.js")>()),
		webdl: async () => Buffer.from("x"),
	}));
	try {
		await g.downloadMmdb();
	} finally {
		vi.doUnmock("../src/pkgman.js");
	}
	expect(g.loadGeoipConfig().name).toBe(DEPRECATED);
	// The stubbed download, not a real one
	expect(fs.readFileSync(g.getMmdbPath("ipv4"), "utf-8")).toBe("x");
});

it("warns on a deprecated source", async () => {
	const { warnings } = await w.recordWarnings(() => {
		g.warnIfDeprecated(g.getGeoipConfigByName(DEPRECATED));
		g.warnIfDeprecated(g.getGeoipConfigByName(DEFAULT));
	});
	expect(warnings.map((x) => x.category)).toEqual(["FutureWarning"]);
	expect(warnings[0].message).toContain(DEFAULT);
});

it.each([
	[0.5, 400, false], // checked today: wait, even for an old build
	[2, 3, false], // this week's build
	[2, 9, true], // a release has been missed
	[40, 3, false], // an old file holding a new build is not stale
	[2, null, true], // unreadable database
])("checked %s days ago, built %s days ago: stale=%s", async (checked, built, stale) => {
	const config = g.loadGeoipConfig();
	const mmdb = g.getMmdbPath("ipv4", config);
	fs.mkdirSync(path.dirname(mmdb), { recursive: true });
	fs.writeFileSync(mmdb, "");
	const stamp = new Date(Date.now() - checked * DAY_MS);
	fs.utimesSync(mmdb, stamp, stamp);
	g.geoipDeps.openDatabase = async () => {
		if (built === null) throw new Error("unreadable");
		return {
			get: () => null,
			metadata: { buildEpoch: new Date(Date.now() - built * DAY_MS) },
		};
	};
	expect(await g.needsUpdate(config)).toBe(stale);
});

it("needs an update when the database is missing", async () => {
	expect(await g.needsUpdate()).toBe(true);
});
