/**
 * Test prerequisites that live outside the repository: the fpgen model, a
 * Python with pythonlib, and Xvfb.
 *
 * On a developer machine a missing one skips the tests that need it, with the
 * reason printed. In CI (GitHub sets CI=true) it FAILS instead: a skip reads as
 * green, so a job that forgot to install something would pass having tested
 * nothing -- which is how these suites came to be skipped on the runner while
 * passing on the machine they were written on. A CI job that genuinely cannot
 * provide one lists it in CAMOUFOX_TEST_ALLOW_MISSING (comma-separated), next to
 * a comment saying why.
 */

const allowedMissing = new Set(
	(process.env.CAMOUFOX_TEST_ALLOW_MISSING ?? "")
		.split(",")
		.map((s) => s.trim())
		.filter(Boolean),
);

/**
 * `ok` when the prerequisite `name` is available. Otherwise false (skip) on a
 * developer machine, and a thrown error -- failing the test file -- in CI.
 */
export function prerequisite(name: string, ok: boolean, detail = ""): boolean {
	if (ok) return true;
	const why = detail ? `${name} (${detail})` : name;
	if (process.env.CI && !allowedMissing.has(name)) {
		throw new Error(
			`test prerequisite missing in CI: ${why}. Install it in the job, or add ` +
				`"${name}" to CAMOUFOX_TEST_ALLOW_MISSING with the reason it cannot be.`,
		);
	}
	console.warn(`[tests] skipping what needs ${why}: not available here`);
	return false;
}
