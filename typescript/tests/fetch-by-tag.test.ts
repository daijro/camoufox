/**
 * Mirrors python/tests/test_fetch_by_tag.py: `camoufox fetch` installs a named
 * build with one GitHub API call, and fails loudly (#919).
 *
 * The CLI runs on import, so each test points XDG_CACHE_HOME at a fresh
 * directory, mocks the network and the install, imports __main__, and waits
 * for the command to install or set an exit code.
 *
 * A test changes what a mock returns through the variables below, never by
 * mocking the module again: vitest registers the mocks queued before an import
 * in the order they resolve, so a second vi.doMock sometimes loses to the first.
 */
import { EventEmitter } from "node:events";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CONSTRAINTS } from "../src/__version__.js";
import type { BrowserPin } from "../src/browser-pin.js";

const API = "https://api.github.com/repos/daijro/camoufox/releases";

let tmp: string;
let savedXdg: string | undefined;
let savedArgv: string[];
let served: Map<string, unknown>;
let requested: string[];
let installs: Array<[string, boolean]>;
let output: string;
let finished: boolean;
let answers: string[];
/** The browser this camoufox release pairs with, as `camoufox fetch` sees it. */
let pin: BrowserPin | null;
let doMock: ReturnType<typeof vi.spyOn>;

/** The modules beforeEach mocks, which a test must not mock again. */
const MOCKED = [
	"../src/browser-pin.js",
	"../src/addons.js",
	"../src/geolocation.js",
	"fpgen-js",
	"node:readline",
];

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-fetch-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	savedArgv = process.argv;
	process.env.XDG_CACHE_HOME = tmp;
	process.exitCode = undefined;
	vi.resetModules();
	served = new Map();
	requested = [];
	installs = [];
	output = "";
	finished = false;
	answers = [];
	pin = null;
	vi.stubGlobal("fetch", async (url: string) => {
		requested.push(url);
		return served.has(url)
			? new Response(JSON.stringify(served.get(url)))
			: new Response("", { status: 404, statusText: "Not Found" });
	});
	vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
		output += String(chunk);
		return true;
	});
	vi.doMock("../src/browser-pin.js", async (load) => ({
		...(await load<typeof import("../src/browser-pin.js")>()),
		effectivePin: () => pin,
	}));
	vi.doMock("../src/geolocation.js", async (load) => ({
		...(await load<typeof import("../src/geolocation.js")>()),
		allowGeoip: () => false,
	}));
	vi.doMock("fpgen-js", async (load) => ({
		...(await load<typeof import("fpgen-js")>()),
		ensureModel: async () => {
			finished = true;
		},
	}));
	// No terminal: stdin holds `answers`, then ends.
	vi.doMock("node:readline", async (load) => ({
		...(await load<typeof import("node:readline")>()),
		createInterface: () => {
			const rl = Object.assign(new EventEmitter(), { close() {} });
			queueMicrotask(() => {
				for (const line of answers) rl.emit("line", line);
				rl.emit("close");
			});
			return rl;
		},
	}));
	doMock = vi.spyOn(vi, "doMock");
});

afterEach(() => {
	// Read before restoreAllMocks below forgets the calls.
	const remocked = doMock.mock.calls
		.map(([module]) => String(module))
		.filter((module) => MOCKED.includes(module));
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	process.argv = savedArgv;
	process.exitCode = undefined;
	for (const module of MOCKED) vi.doUnmock(module);
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
	fs.rmSync(tmp, { recursive: true, force: true });
	expect(remocked, "mocked again; set what its mock reads").toEqual([]);
});

async function release(
	tag: string,
	build: string,
	{ version = "156.0.1", prerelease = false } = {},
) {
	const { RepoConfig } = await import("../src/pkgman.js");
	const official = RepoConfig.getDefault();
	const manifest = `https://example.invalid/${tag}/manifest.json`;
	served.set(manifest, { interface: CONSTRAINTS.INTERFACE });
	return {
		tag_name: tag,
		prerelease,
		assets: [
			{
				name: `camoufox-${version}-${build}-${official.getOsName()}.${official.getArch()}.zip`,
				browser_download_url: `https://example.invalid/${tag}/browser.zip`,
				digest: `sha256:${"ab".repeat(32)}`,
				created_at: "2026-10-01T00:00:00Z",
			},
			{ name: "manifest.json", id: tag, browser_download_url: manifest },
		],
	};
}

async function onlyOfficialSource() {
	const { RepoConfig } = await import("../src/pkgman.js");
	const official = RepoConfig.getDefault();
	vi.spyOn(RepoConfig, "loadRepos").mockReturnValue([official]);
}

async function fetchCommand(...args: string[]) {
	const { CamoufoxFetcher } = await import("../src/pkgman.js");
	vi.spyOn(CamoufoxFetcher.prototype, "install").mockImplementation(
		async function (this: InstanceType<typeof CamoufoxFetcher>) {
			installs.push([this.verstr, this.isPrerelease]);
		},
	);
	process.argv = ["node", "camoufox", "fetch", ...args];
	await import("../src/__main__.js");
	await vi.waitFor(() => {
		if (!finished && process.exitCode === undefined)
			throw new Error("fetch is still running");
	});
}

const apiRequests = () =>
	requested.filter((url) => url.startsWith("https://api.github.com/"));

it("fetches a named build with one API call", async () => {
	served.set(
		`${API}/tags/v156.0.1-beta.33`,
		await release("v156.0.1-beta.33", "beta.33"),
	);

	await fetchCommand("official/156.0.1-beta.33");

	expect(process.exitCode ?? 0).toBe(0);
	expect(apiRequests()).toEqual([`${API}/tags/v156.0.1-beta.33`]);
	expect(installs).toEqual([["156.0.1-beta.33", false]]);
});

it("fetches the paired build with one API call", async () => {
	pin = {
		tag: "v156.0.1-beta.33",
		repo: "daijro/camoufox",
		repoName: "official",
		version: "156.0.1",
		build: "beta.33",
	};
	served.set(
		`${API}/tags/v156.0.1-beta.33`,
		await release("v156.0.1-beta.33", "beta.33", { prerelease: true }),
	);

	await fetchCommand();

	expect(process.exitCode ?? 0).toBe(0);
	expect(apiRequests()).toEqual([`${API}/tags/v156.0.1-beta.33`]);
	expect(installs).toEqual([["156.0.1-beta.33", true]]);
});

it("finds a build without its own tag by syncing", async () => {
	// Early alphas were published under other tags (v146-hardware holds 146.0.1-alpha.25).
	await onlyOfficialSource();
	served.set(API, [
		await release("v146-hardware", "alpha.25", { version: "146.0.1" }),
	]);
	answers = ["y"];

	await fetchCommand("official/146.0.1-alpha.25");

	expect(process.exitCode ?? 0).toBe(0);
	expect(installs).toEqual([["146.0.1-alpha.25", true]]);
});

it("fails the fetch for a build that does not exist", async () => {
	await onlyOfficialSource();
	served.set(API, []);

	await fetchCommand("official/156.0.1-beta.99");

	expect(process.exitCode).toBe(1);
	expect(output).toContain("not found");
	expect(installs).toEqual([]);
});

it("fails the fetch when the install fails", async () => {
	served.set(
		`${API}/tags/v156.0.1-beta.33`,
		await release("v156.0.1-beta.33", "beta.33"),
	);
	const { CamoufoxFetcher } = await import("../src/pkgman.js");
	const install = vi.spyOn(CamoufoxFetcher.prototype, "install");

	process.argv = ["node", "camoufox", "fetch", "official/156.0.1-beta.33"];
	install.mockRejectedValue(
		new Error(
			"404 Client Error: Not Found for url: https://example.invalid/browser.zip",
		),
	);
	await import("../src/__main__.js");
	await vi.waitFor(() => {
		if (process.exitCode === undefined)
			throw new Error("fetch is still running");
	});

	expect(process.exitCode).toBe(1);
	expect(output).toContain("Release not found (404)");
});

it("fails the fetch when the lookup is rate limited", async () => {
	await onlyOfficialSource();
	vi.stubGlobal("fetch", async (url: string) => {
		requested.push(url);
		return new Response("", { status: 403, statusText: "rate limit exceeded" });
	});

	await fetchCommand("official/156.0.1-beta.33");

	expect(process.exitCode).toBe(1);
	expect(output).toContain("403");
	expect(installs).toEqual([]);
});

it("fails the fetch when nobody confirms a prerelease", async () => {
	// CI has no terminal to answer the prerelease prompt; the fetch must not pass.
	served.set(
		`${API}/tags/v158.0-beta.40`,
		await release("v158.0-beta.40", "beta.40", {
			version: "158.0",
			prerelease: true,
		}),
	);

	await fetchCommand("official/158.0-beta.40");

	expect(process.exitCode).toBe(1);
	expect(output).toContain("Installation cancelled.");
	expect(installs).toEqual([]);
});
