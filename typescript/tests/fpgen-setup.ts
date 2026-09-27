/**
 * Shared setup for the fpgen tests: the model, the Python golden fixtures, and
 * the named predicates they refer to.
 *
 * The model is the pinned one (src/fpgen/pin.ts), fetched into the Camoufox
 * cache on first run -- or read from $CAMOUFOX_FPGEN_DATA. When it is neither
 * cached nor downloadable (offline CI), the model-dependent suites skip with
 * the reason printed rather than failing.
 *
 * Fixtures come from scripts/golden/fpgen_golden.py (run with the worktree's
 * .venv, which has fpgen 1.3.0 and the same pinned model).
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { ensureModel } from "../src/fpgen/index.js";
import { prerequisite } from "./prereq.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FIXTURES = path.join(HERE, "fixtures", "fpgen");

export function fixture<T = any>(name: string): T {
	return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), "utf-8"));
}

async function prepare(): Promise<{ ok: boolean; reason?: string }> {
	try {
		await ensureModel();
		return { ok: true };
	} catch (e) {
		const reason = `not cached and could not be downloaded: ${(e as Error).message}`;
		prerequisite("fpgen-model", false, reason);
		return { ok: false, reason };
	}
}

/** Resolved once per test file (vitest isolates files). */
export const MODEL = await prepare();

/** The predicates named in the fixtures. Python passes them casefolded values. */
export const PREDICATES: Record<string, (v: any) => boolean> = {
	screen_width_1280_1920: (w) => Number.isInteger(w) && w >= 1280 && w <= 1920,
	os_linux_or_windows: (v) => v === "linux" || v === "windows",
	hc_at_least_8: (v) => Number.isInteger(v) && v >= 8,
	ua_rv146: (v) => typeof v === "string" && v.includes("rv:146"),
	never: () => false,
};

/** Fixture conditions -> TS conditions ({$pred} -> function, {$alt} -> Set). */
export function fromFixture(cond: any): any {
	if (cond === null || typeof cond !== "object" || Array.isArray(cond)) {
		return cond;
	}
	if ("$pred" in cond) return PREDICATES[cond.$pred];
	if ("$alt" in cond) return new Set(cond.$alt.map(fromFixture));
	const out: Record<string, any> = {};
	for (const [k, v] of Object.entries(cond)) out[k] = fromFixture(v);
	return out;
}
