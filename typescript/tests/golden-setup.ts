/**
 * vitest globalSetup: record the golden fixtures from pythonlib before any test
 * reads them.
 *
 * The goldens are pythonlib's own output over fixed inputs
 * (scripts/golden/*.py -> tests/fixtures/{launch,identity,fpgen}). They are
 * regenerated on every run rather than committed, so the TS tests always
 * compare against the pythonlib in this checkout: a pythonlib change that
 * typescript/ does not mirror fails here. fpgen's stats.json is the exception --
 * thousands of random draws, compared statistically, that change with the
 * pinned model rather than with pythonlib -- and stays committed.
 */
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(
	path.dirname(fileURLToPath(import.meta.url)),
	"..",
	"..",
);

/** The interpreter with pythonlib installed: $CAMOUFOX_PYTHON, else the repo's .venv. */
export const PYTHON =
	process.env.CAMOUFOX_PYTHON ??
	path.join(
		REPO,
		".venv",
		process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
	);

const GENERATORS: string[][] = [
	["launch_golden.py"],
	["identity_golden.py"],
	["fpgen_golden.py", "structure", "values", "conditions", "api"],
];

export default function setup(): void {
	if (!fs.existsSync(PYTHON)) {
		throw new Error(
			`The golden fixtures are recorded from pythonlib, and ${PYTHON} does not exist. ` +
				"From the repo root:\n" +
				"  python3.14 -m venv .venv\n" +
				"  .venv/bin/pip install -r ci/requirements.txt -e pythonlib\n" +
				"  .venv/bin/python scripts/pin-fpgen-model.py\n" +
				"or point CAMOUFOX_PYTHON at an interpreter that has them.",
		);
	}
	for (const [script, ...args] of GENERATORS) {
		const proc = spawnSync(
			PYTHON,
			[path.join(REPO, "typescript", "scripts", "golden", script), ...args],
			{ cwd: REPO, encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] },
		);
		if (proc.status !== 0) {
			throw new Error(
				`${script} exited ${proc.status ?? proc.signal}:\n${proc.stderr}`,
			);
		}
	}
}
