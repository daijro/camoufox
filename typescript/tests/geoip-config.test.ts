/**
 * Mirrors python/tests/test_geoip_config.py: the CLI's handling of the GeoIP
 * source. Which source is active, and when its database is refreshed, is
 * camoucore's (its tests/geoip-config.test.ts).
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let tmp: string;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-geoip-"));
});

afterEach(() => {
	vi.doUnmock("camoucore/geolocation.js");
	fs.rmSync(tmp, { recursive: true, force: true });
});

it("the CLI reports an explicit source missing from the list", async () => {
	const { ValueError } = await import("../src/pycompat.js");
	vi.doMock("camoucore/geolocation.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("camoucore/geolocation.js")>()),
		GEOIP_DIR: tmp,
		loadGeoipConfig: () => {
			throw new ValueError("GeoIP database 'Gone' not found. Available: []");
		},
	}));
	const savedArgv = process.argv;
	let output = "";
	const write = vi
		.spyOn(process.stdout, "write")
		.mockImplementation((chunk) => {
			output += String(chunk);
			return true;
		});
	try {
		for (const command of ["version", "list"]) {
			vi.resetModules();
			process.argv = ["node", "camoufox", command];
			await import("../src/__main__.js");
			await new Promise((resolve) => setTimeout(resolve, 0));
		}
	} finally {
		write.mockRestore();
		process.argv = savedArgv;
	}
	expect(process.exitCode ?? 0).toBe(0);
	expect(output.match(/'Gone' not found/g)).toHaveLength(2);
});
