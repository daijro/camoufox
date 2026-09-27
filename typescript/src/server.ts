/**
 * Playwright server mode.
 *
 * TypeScript twin of pythonlib/camoufox/server.py. Python has to shell out to
 * the Node runtime bundled with its Playwright driver (and hand it a base64
 * config frame over stdin, via launchServer.js) because there is no Python
 * binding for BrowserServer. Here we already are that runtime, so this calls
 * playwright-core's launchServer() directly with the same options Python
 * would send: launchOptions() with every top-level key camelCased.
 */
import { type BrowserServer, firefox } from "playwright-core";
import { withUnpinnedLaunch } from "./cpu_affinity.js";
import { camelCase } from "./sync_api.js";
import { type LaunchOptions, launchOptions } from "./utils.js";
import { VirtualDisplay } from "./virtdisplay.js";

export interface LaunchServerOptions extends Omit<LaunchOptions, "headless"> {
	/** Port to listen on. Defaults to a random free port. */
	port?: number;
	/** Path of the websocket endpoint. Defaults to a random path. */
	ws_path?: string;
	/** Whether to run the browser headless. `"virtual"` spawns an Xvfb display
	 * (a TS extension: Python's launch_server passes headless through). */
	headless?: boolean | "virtual";
}

/**
 * Convert a dictionary's keys to camelCase (server.to_camel_case_dict). Keys
 * without an underscore are already JS names and are kept as they are.
 */
export function toCamelCaseDict(
	data: Record<string, any>,
): Record<string, any> {
	const out: Record<string, any> = {};
	for (const [key, value] of Object.entries(data)) {
		out[key.includes("_") ? camelCase(key) : key] = value;
	}
	return out;
}

/**
 * Launch a Playwright server. Takes the same options as `Camoufox()`.
 *
 * Note: persistent contexts are not servable. Playwright's `launchServer`
 * routes through `BrowserType.launch()`, and its `PlaywrightServer` only
 * accepts a pre-launched Browser -- there is no way to expose a persistent
 * BrowserContext over a websocket endpoint. Reject those options up front
 * rather than accepting them and silently launching a throwaway profile.
 */
export async function launchServer({
	headless,
	...options
}: LaunchServerOptions = {}): Promise<BrowserServer> {
	for (const unsupported of ["persistent_context", "user_data_dir"] as const) {
		if (options[unsupported]) {
			throw new Error(
				`launch_server() does not support '${unsupported}': Playwright cannot ` +
					"serve a persistent context over a websocket endpoint. Use " +
					"Camoufox(persistent_context=True, ...) in-process instead.",
			);
		}
		delete options[unsupported];
	}

	let virtualDisplay: VirtualDisplay | null = null;
	let headlessBool: boolean | undefined;
	if (headless === "virtual") {
		virtualDisplay = new VirtualDisplay(options.debug ?? false);
		options.virtual_display = await virtualDisplay.get();
		headlessBool = false;
	} else {
		headlessBool = headless;
	}

	try {
		const config = await launchOptions({ ...options, headless: headlessBool });
		// The server's browser is spawned from this process too, so it must not
		// start inside another launch's CPU pin.
		const server = await withUnpinnedLaunch(() =>
			firefox.launchServer(toCamelCaseDict(config)),
		);

		if (virtualDisplay) {
			// BrowserServer has no "disconnected" event; "close" fires on shutdown.
			const display = virtualDisplay;
			server.on("close", () => display.kill());
		}

		return server;
	} catch (error) {
		virtualDisplay?.kill();
		throw error;
	}
}
