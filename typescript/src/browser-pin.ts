/**
 * The browser build this copy of the library was released with.
 *
 * Twin of pythonlib/camoufox/browser_pin.py, reading the same
 * `browser-pin.json` (a DATA_FILES entry). Every published package is stamped
 * with the one browser release built from the same sources; by default the
 * library fetches and launches exactly that build. An explicit user choice
 * (`camoufox set ...`) is kept, with a warning at launch. A development
 * checkout carries `{}` and pins nothing.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { LOCAL_DATA } from "./paths.js";
import { warn } from "./warnings.js";

/** Test seam, like pkgmanDeps: where the pin is read from. */
export const browserPinDeps = {
	file: path.join(LOCAL_DATA, "browser-pin.json"),
};

export interface BrowserPin {
	tag: string;
	repo: string;
	repoName: string;
	version: string;
	build: string;
}

/** `<firefox version>-<build>`, the form `camoufox set` and the cache use. */
export function pinSpec(pin: BrowserPin): string {
	return `${pin.version}-${pin.build}`;
}

/** The stamped pin, or null for an unpinned (development) copy. */
export function loadPin(file: string = browserPinDeps.file): BrowserPin | null {
	let data: Record<string, string | null>;
	try {
		data = JSON.parse(fs.readFileSync(file, "utf-8"));
	} catch {
		return null;
	}
	if (!data?.tag) return null;
	return {
		tag: data.tag,
		repo: String(data.repo),
		repoName: String(data.repo_name).toLowerCase(),
		version: String(data.version),
		build: String(data.build),
	};
}

/** Whether the user chose a channel or a build themselves. */
export function isExplicitChoice(config: {
	channel?: string;
	pinned?: string;
}): boolean {
	return Boolean(config.channel || config.pinned);
}

/** The package pin, unless the user explicitly chose otherwise. */
export function effectivePin(config: {
	channel?: string;
	pinned?: string;
}): BrowserPin | null {
	const pin = loadPin();
	return pin && !isExplicitChoice(config) ? pin : null;
}

export function pinMatches(
	pin: BrowserPin,
	repoName: string,
	version: string,
	build: string,
): boolean {
	return (
		repoName.toLowerCase() === pin.repoName &&
		version === pin.version &&
		build === pin.build
	);
}

let warned = false;

/** Warn once when an explicitly chosen build is not the one this library pairs with. */
export function warnIfUnpaired(
	repoName: string,
	version: string,
	build: string,
): void {
	const pin = loadPin();
	if (warned || pin === null || pinMatches(pin, repoName, version, build)) {
		return;
	}
	warned = true;
	warn(
		`Launching ${repoName.toLowerCase()} ${version}-${build}, which you selected explicitly. ` +
			`This camoufox release was built and tested with ${pin.repoName} ${pinSpec(pin)} ` +
			`(${pin.tag}); other builds may not be compatible. ` +
			"Run `camoufox set --release` to go back to the paired build.",
	);
}

/** Test hook: forget that the warning was already issued. */
export function resetUnpairedWarning(): void {
	warned = false;
}
