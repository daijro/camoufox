/**
 * Default Firefox addons: the ones each browser release bundles.
 *
 * TypeScript twin of python/src/camoufox/addons.py.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { InvalidAddonPath } from "./exceptions.js";
import { buildFile } from "./pkgman.js";
import { loadWarnings, warn } from "./warnings.js";

/**
 * Default addons. Each browser release bundles them, extracted, under
 * addons/<name>/ beside its binary (browser/scripts/fetch-ubo.py).
 */
export const DefaultAddons = {
	UBO: "UBO",
} as const;

export type DefaultAddon = keyof typeof DefaultAddons;

/**
 * Confirms that the addon paths are valid.
 */
export function confirmPaths(paths: string[]): void {
	for (const addonPath of paths) {
		if (!fs.existsSync(addonPath) || !fs.statSync(addonPath).isDirectory()) {
			throw new InvalidAddonPath(addonPath);
		}
		if (!fs.existsSync(path.join(addonPath, "manifest.json"))) {
			throw new InvalidAddonPath(
				"manifest.json is missing. Addon path must be a path to an extracted addon.",
			);
		}
	}
}

/**
 * Returns the path to the addon the build at executablePath bundles.
 */
export function getAddonPath(
	addonName: string,
	executablePath: string,
): string {
	return buildFile(executablePath, path.join("addons", addonName));
}

/**
 * Adds the default addons the build at executablePath bundles, minus any
 * specified in excludeList, to addonsList.
 */
export function addDefaultAddons(
	addonsList: string[],
	excludeList: DefaultAddon[] | undefined,
	executablePath: string,
): void {
	for (const name of Object.keys(DefaultAddons) as DefaultAddon[]) {
		if (excludeList?.includes(name)) continue;
		const addonPath = getAddonPath(name, executablePath);
		// A build released before the addons were bundled, or an unpackaged
		// one, has none. It still launches, but not as the browser asked for.
		if (!fs.existsSync(path.join(addonPath, "manifest.json"))) {
			warn(
				loadWarnings()
					.addon_not_bundled.replaceAll("{addon}", name)
					.replace("{path}", addonPath),
			);
			continue;
		}
		addonsList.push(addonPath);
	}
}
