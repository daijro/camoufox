/**
 * Port of pythonlib/tests/test_cli_list.py: `camoufox list --path` shows
 * install paths in both listing modes.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let tmp: string;
let savedXdg: string | undefined;
let savedArgv: string[];

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-cli-"));
	savedXdg = process.env.XDG_CACHE_HOME;
	savedArgv = process.argv;
	process.env.XDG_CACHE_HOME = tmp;
	vi.resetModules();
});

afterEach(() => {
	if (savedXdg === undefined) delete process.env.XDG_CACHE_HOME;
	else process.env.XDG_CACHE_HOME = savedXdg;
	process.argv = savedArgv;
	vi.doUnmock("../src/multiversion.js");
	vi.restoreAllMocks();
	fs.rmSync(tmp, { recursive: true, force: true });
});

it("list all --path shows the path of an installed build", async () => {
	const install = "/cache/browsers/official/152.0.4-beta.30";
	const actual = await import("../src/multiversion.js");
	const { Version } = await import("../src/pkgman.js");
	fs.mkdirSync(path.dirname(actual.REPO_CACHE_FILE), { recursive: true });
	fs.writeFileSync(
		actual.REPO_CACHE_FILE,
		JSON.stringify({
			repos: [
				{
					name: "official",
					versions: [{ version: "152.0.4", build: "beta.30" }],
				},
			],
		}),
	);
	const installed = new actual.InstalledVersion({
		repoName: "official",
		version: new Version("beta.30", "152.0.4"),
		path: install,
	});
	vi.doMock("../src/multiversion.js", () => ({
		...actual,
		listInstalled: () => [installed],
	}));

	let output = "";
	vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
		output += String(chunk);
		return true;
	});
	process.argv = ["node", "camoufox", "list", "all", "--path"];
	await import("../src/__main__.js");
	await new Promise((resolve) => setTimeout(resolve, 0));
	vi.mocked(process.stdout.write).mockRestore();

	expect(process.exitCode ?? 0).toBe(0);
	expect(output).toContain(install);
});
