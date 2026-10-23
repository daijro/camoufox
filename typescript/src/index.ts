/**
 * Public API. Mirrors python/src/camoufox/__init__.py (Camoufox, NewBrowser,
 * NewContext, their Async* twins, DefaultAddons, launch_options), plus the
 * package-management and server helpers the TS port has always exported.
 */
export type { DefaultAddon } from "./addons.js";
export { DefaultAddons } from "./addons.js";
export {
	AsyncCamoufox,
	AsyncNewBrowser,
	AsyncNewContext,
} from "./async_api.js";
export {
	generateContextFingerprint,
	getRandomPreset,
	loadPresets,
	Screen,
} from "./fingerprints.js";
export {
	findInstalledVersion,
	listInstalled,
	printTree,
} from "./multiversion.js";
export { INSTALL_DIR, OS_NAME } from "./paths.js";
export { CamoufoxFetcher, installedVerStr, RepoConfig } from "./pkgman.js";
export { type LaunchServerOptions, launchServer } from "./server.js";
export {
	Camoufox,
	type Headless,
	NewBrowser,
	type NewBrowserOptions,
	NewContext,
	type NewContextOptions,
} from "./sync_api.js";
export {
	type LaunchOptions,
	launchOptions,
	launchOptions as launch_options,
} from "./utils.js";
export { VirtualDisplay } from "./virtdisplay.js";
export { FallbackWarning, LeakWarning } from "./warnings.js";
