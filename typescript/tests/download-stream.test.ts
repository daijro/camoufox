/**
 * The browser download writes through a file stream. A failed write (disk
 * full) must come back as an ordinary rejection that installVersioned() cleans
 * up after -- an 'error' event with no listener kills the process instead --
 * and a slow disk must hold the download back rather than queue it in memory.
 */
import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { Writable } from "node:stream";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let tmp: string;
let savedXdg: string | undefined;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-dl-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	vi.unstubAllGlobals();
	fs.rmSync(tmp, { recursive: true, force: true });
});

it("a failed write rejects, and the partial install is removed", async () => {
	const { installVersioned, BROWSERS_DIR } = await import(
		"../src/multiversion.js"
	);
	const { CamoufoxFetcher } = await import("../src/pkgman.js");

	class DiskFull extends CamoufoxFetcher {
		static override async downloadFile(file: Writable): Promise<void> {
			file.write(Buffer.alloc(1024));
			file.destroy(
				Object.assign(new Error("ENOSPC: no space left"), { code: "ENOSPC" }),
			);
			await new Promise((r) => setTimeout(r, 20));
		}
	}
	// Skip the constructor: it would query GitHub.
	const fetcher = Object.create(DiskFull.prototype);
	const own = (value: unknown) => ({ value, configurable: true });
	Object.defineProperties(fetcher, {
		githubRepo: own("example/camoufox"),
		version: own("152.0.4"),
		build: own("beta.99"),
		verstr: own("152.0.4-beta.99"),
		url: own("https://example.invalid/camoufox.zip"),
		_selectedVersion: own(null),
	});

	await expect(installVersioned(fetcher)).rejects.toThrow(/ENOSPC/);
	expect(
		fs.existsSync(path.join(BROWSERS_DIR, "example", "152.0.4-beta.99")),
	).toBe(false);
});

it("waits for a slow stream to drain instead of queueing the download", async () => {
	const { webdl } = await import("../src/pkgman.js");
	const chunks = 64;
	const size = 1024;
	vi.stubGlobal(
		"fetch",
		async () =>
			new Response(
				new ReadableStream({
					start(controller) {
						for (let i = 0; i < chunks; i++)
							controller.enqueue(new Uint8Array(size));
						controller.close();
					},
				}),
				{ headers: { "content-length": String(chunks * size) } },
			),
	);
	let peak = 0;
	let received = 0;
	const slow: Writable = new Writable({
		highWaterMark: size,
		write(chunk, _enc, done) {
			received += chunk.length;
			setTimeout(() => {
				// What is still queued behind this chunk once the disk catches up.
				peak = Math.max(peak, slow.writableLength);
				done();
			}, 2);
		},
	});
	await webdl("https://example.invalid/x.zip", "x", false, slow, {
		progressCallback: () => {},
	});
	await new Promise<void>((r) => slow.end(r));
	expect(received).toBe(chunks * size);
	// Without waiting for 'drain' all 64 KiB sit in the stream's buffer.
	expect(peak).toBeLessThanOrEqual(2 * size);
});

it("a network failure names the URL and its cause", async () => {
	// Node's own error is only "fetch failed".
	const { webdl } = await import("../src/pkgman.js");
	// A port that was just free, so nothing is listening on it.
	const server = net.createServer();
	await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
	const { port } = server.address() as net.AddressInfo;
	await new Promise((resolve) => server.close(resolve));
	const url = `http://127.0.0.1:${port}/geoip.zip`;
	await expect(webdl(url, "x", false)).rejects.toThrow(
		`Could not download ${url}: fetch failed (ECONNREFUSED`,
	);
});
