#!/usr/bin/env node
/**
 * The npm twin of `twine check`: prove the tarball `npm publish` would upload is
 * a working package before it goes anywhere.
 *
 *   1. its version equals pythonlib's (the two launchers ship in lockstep, and
 *      a user comparing `camoufox version` across them should see one number);
 *   2. it carries every file src/ reads at runtime -- the DATA_FILES it takes
 *      from pythonlib and any non-TS file under src/ -- since a file missing
 *      only shows up on a user's machine, as an ENOENT from inside dist/;
 *   3. installed into an empty project, it imports and exposes its entry
 *      points, and its CLI starts.
 *
 * Run after `pnpm build`: node scripts/check-pack.mjs
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const problems = [];

// 1. version lockstep with pythonlib
const pyproject = readFileSync(join(root, "..", "pythonlib", "pyproject.toml"), "utf8");
const pyVersion = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
// One release, spelled for each registry: npm's 0.5.8-beta.2 is PyPI's 0.5.8b2.
const asPep440 = (v) => v.replace(/-beta\.(\d+)$/, "b$1");
if (pyVersion !== asPep440(pkg.version)) {
	problems.push(`package.json version ${pkg.version} != pythonlib ${pyVersion}`);
}
if (pkg.private) problems.push("package.json is private: npm will refuse to publish it");

// 2. every runtime data file is in the tarball
// npm 10 still runs `prepare` (the build) on pack despite --ignore-scripts, and
// its banner lands on stdout ahead of the JSON.
const packOut = execFileSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
	cwd: root,
	encoding: "utf8",
});
const packed = JSON.parse(packOut.slice(packOut.search(/^\[/m)))[0];
const inTarball = new Set(packed.files.map((f) => f.path));
function walk(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
		e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
	);
}
const src = join(root, "src");
for (const file of walk(src)) {
	const rel = relative(src, file);
	if (/\.ts$/.test(rel)) {
		const js = `dist/${rel.replace(/\.ts$/, ".js")}`;
		if (!rel.endsWith(".d.ts") && !inTarball.has(js)) problems.push(`missing ${js}`);
	} else if (!inTarball.has(`dist/${rel}`)) {
		problems.push(`missing dist/${rel} (a non-TS file under src/ that copy-files does not ship)`);
	}
}
const { DATA_FILES } = await import(join(root, "dist", "paths.js"));
for (const name of DATA_FILES) {
	if (!inTarball.has(`dist/data-files/${name}`)) problems.push(`missing dist/data-files/${name}`);
}
console.log(`${packed.filename}: ${packed.entryCount} files, ${(packed.size / 1e6).toFixed(1)} MB packed`);

// 3. installs and imports in a clean project
if (problems.length === 0) {
	const tmp = mkdtempSync(join(tmpdir(), "camoufox-pack-"));
	try {
		const tgz = execFileSync("npm", ["pack", "--ignore-scripts", "--pack-destination", tmp], {
			cwd: root,
			encoding: "utf8",
		})
			.trim()
			.split("\n")
			.pop();
		writeFileSync(join(tmp, "package.json"), '{"name":"pack-check","private":true,"type":"module"}');
		execFileSync("npm", ["install", "--no-audit", "--no-fund", join(tmp, tgz), `playwright-core@${pkg.peerDependencies["playwright-core"]}`], {
			cwd: tmp,
			stdio: "inherit",
		});
		const probe = `
			const m = await import(${JSON.stringify(pkg.name)});
			for (const name of ["Camoufox", "NewBrowser", "launchOptions"]) {
				if (typeof m[name] !== "function") throw new Error("missing export " + name);
			}
			console.log("exports:", Object.keys(m).length);
		`;
		execFileSync("node", ["--input-type=module", "-e", probe], { cwd: tmp, stdio: "inherit" });
		for (const bin of Object.keys(pkg.bin ?? {})) {
			execFileSync("npx", ["--no-install", bin, "--help"], { cwd: tmp, stdio: "ignore" });
		}
	} catch (err) {
		problems.push(`clean install failed: ${err.message}`);
	} finally {
		rmSync(tmp, { recursive: true, force: true });
	}
}

if (problems.length) {
	console.error(problems.map((p) => `  - ${p}`).join("\n"));
	process.exit(1);
}
console.log("pack check OK");
