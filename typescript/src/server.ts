/**
 * Playwright server mode.
 *
 * TypeScript twin of python/src/camoufox/server.py. Python has to shell out to
 * the Node runtime bundled with its Playwright driver (and hand it a base64
 * config frame over stdin, via launchServer.js) because there is no Python
 * binding for BrowserServer. Here we already are that runtime, so this calls
 * playwright-core's launchServer() directly with the same options Python
 * would send: launchOptions() with every top-level key camelCased.
 */
import { type BrowserServer, firefox } from "playwright-core";
import { withUnpinnedLaunch } from "./cpu_affinity.js";
import { GpuDisplay, proveGpu } from "./gpudisplay.js";
import { camelCase } from "./sync_api.js";
import {
	type GpuDisplayOptions,
	type Headless,
	type LaunchOptions,
	launchOptions,
	startVirtualDisplay,
} from "./utils.js";

export interface LaunchServerOptions
	extends Omit<LaunchOptions, "headless">,
		GpuDisplayOptions {
	/** Port to listen on. Defaults to a random free port. */
	port?: number;
	/** Path of the websocket endpoint. Defaults to a random path. */
	ws_path?: string;
	/** Whether to run the browser headless. `"virtual"` spawns an Xvfb display,
	 * `"virtual-gpu"` a headless Xorg server bound to one GPU. */
	headless?: Headless;
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

	const [virtualDisplay, headlessBool] = await startVirtualDisplay(
		headless,
		options.debug,
		options,
	);

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
		if (virtualDisplay instanceof GpuDisplay) {
			const browser = await firefox.connect(server.wsEndpoint());
			try {
				await proveGpu(browser, virtualDisplay);
			} catch (error) {
				await server.close();
				throw error;
			} finally {
				await browser.close();
			}
		}

		return server;
	} catch (error) {
		virtualDisplay?.kill();
		throw error;
	}
}
