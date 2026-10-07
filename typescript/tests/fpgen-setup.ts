/**
 * Shared setup for the fpgen tests: the pinned model (read from where camoufox
 * keeps it, so the suites share one copy), the golden fixtures recorded by
 * scripts/golden/fpgen_golden.py, and the named predicates those refer to.
 * A model that can be neither read nor downloaded is a missing prerequisite.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { ensureModel } from "fpgen";
import "../src/paths.js";
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
