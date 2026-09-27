/**
 * TypeScript twin of pythonlib/camoufox/async_api.py.
 *
 * playwright-core has a single, promise-based API, so the async entry points
 * are the same functions as sync_api.ts under Python's async names. The
 * behaviours async_api.py adds over sync_api.py (the per-driver pin lock) live
 * there already.
 */
export {
	Camoufox as AsyncCamoufox,
	NewBrowser as AsyncNewBrowser,
	type NewBrowserOptions,
	NewContext as AsyncNewContext,
	type NewContextOptions,
} from "./sync_api.js";
