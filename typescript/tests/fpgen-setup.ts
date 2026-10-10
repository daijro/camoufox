/**
 * Shared setup for the fpgen tests: the pinned model, read from where camoufox
 * keeps it, so the suites share one copy. A model that can be neither read nor
 * downloaded is a missing prerequisite.
 */
import { ensureModel } from "fpgen-js";
import "../src/paths.js";
import { prerequisite } from "./prereq.js";

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
