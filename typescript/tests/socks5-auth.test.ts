/**
 * A SOCKS5 proxy with a username and password reaches Juggler, not
 * Playwright. Twin of python/tests/test_socks5_auth.py.
 */

import * as fs from "node:fs";
import { afterAll, afterEach, describe, expect, it } from "vitest";
import {
	HOME,
	isolateLaunch,
	quietly,
	restoreDeps,
	SCRATCH,
	utils,
} from "./launch-host.js";

const ip = await import("../src/ip.js");

afterEach(() => restoreDeps());
afterAll(() => fs.rmSync(SCRATCH, { recursive: true, force: true }));

const SOCKS = {
	server: "socks5://127.0.0.1:1080",
	username: "user+denver+os-linux",
	password: "pw",
};
const AUTH = {
	host: "127.0.0.1",
	port: 1080,
	username: "user+denver+os-linux",
	password: "pw",
};

/** What TargetRegistry.js takeProxyAuth() reads from a context's script,
 * after Playwright wraps the body in `(() => { ... })();`. */
function jugglerReads(script: string): unknown {
	const wrapped = `(() => {\n        ${script}\n      })();`;
	const body = (
		/^\s*\(\(\)\s*=>\s*\{([\s\S]*)\}\)\(\);?\s*$/.exec(
			wrapped,
		) as RegExpExecArray
	)[1].trim();
	expect(body.startsWith("camoufoxProxyAuth:")).toBe(true);
	return JSON.parse(
		body
			.slice("camoufoxProxyAuth:".length)
			.trim()
			.replace(/^\(/, "")
			.replace(/\);?$/, ""),
	);
}

describe("socks5Auth", () => {
	it.each([
		[SOCKS, { server: "socks5://127.0.0.1:1080" }, AUTH],
		[
			{ server: "SOCKS5://[::1]:9", username: "u" },
			{ server: "SOCKS5://[::1]:9" },
			{ host: "::1", port: 9, username: "u", password: "" },
		],
		[
			{
				server: "socks5://proxy.example",
				username: "u",
				password: "p",
				bypass: "a.test",
			},
			{ server: "socks5://proxy.example", bypass: "a.test" },
			{ host: "proxy.example", port: null, username: "u", password: "p" },
		],
	])("splits the credentials off %j", (proxy, bare, auth) => {
		const before = structuredClone(proxy);
		expect(ip.socks5Auth(proxy)).toEqual([bare, auth]);
		expect(proxy).toEqual(before);
	});

	it.each([
		[undefined],
		[{ server: "socks5://127.0.0.1:1080" }],
		[{ server: "http://127.0.0.1:8080", username: "u", password: "p" }],
		[{ server: "127.0.0.1:1080", username: "u", password: "p" }],
		[{ server: "socks4://127.0.0.1:1080", username: "u" }],
	])("leaves %j to Playwright", (proxy) => {
		expect(ip.socks5Auth(proxy)).toEqual([proxy, null]);
	});

	it("carries any password through the init script", () => {
		const tricky = { ...AUTH, password: 'p"});\n})();alert(1)// ' };
		expect(jugglerReads(ip.proxyAuthInitScript(tricky))).toEqual(tricky);
	});
});

describe("launchOptions", () => {
	const launch = (proxy: Record<string, any>) => {
		isolateLaunch();
		return quietly(() =>
			utils.launchOptions({
				env: { HOME },
				proxy,
				geoip: false,
				headless: true,
				block_webgl: true,
				i_know_what_im_doing: true,
			}),
		) as Promise<Record<string, any>>;
	};

	it("hands launch-level SOCKS5 credentials to Juggler", async () => {
		const options = await launch({ ...SOCKS });
		expect(options.proxy).toEqual({ server: "socks5://127.0.0.1:1080" });
		expect(JSON.parse(options.env[ip.PROXY_AUTH_ENV])).toEqual(AUTH);
		expect(JSON.stringify(options.args)).not.toContain("pw");
		expect(JSON.stringify(options.firefoxUserPrefs)).not.toContain('"pw"');
	});

	it("leaves HTTP proxy credentials with Playwright", async () => {
		const proxy = {
			server: "http://127.0.0.1:8080",
			username: "u",
			password: "p",
		};
		const options = await launch({ ...proxy });
		expect(options.proxy).toEqual(proxy);
		expect(ip.PROXY_AUTH_ENV in options.env).toBe(false);
	});
});

describe("attachSocks5Auth", () => {
	function fakeBrowser() {
		const calls: any[] = [];
		const scripts: string[] = [];
		const browser = {
			async newContext(options?: Record<string, any>) {
				calls.push(options);
				return {
					async addInitScript(script: string) {
						scripts.push(script);
					},
				};
			},
		};
		return { browser, calls, scripts };
	}

	it("sends a context's credentials in an init script", async () => {
		const { browser, calls, scripts } = fakeBrowser();
		utils.attachSocks5Auth(browser);
		utils.attachSocks5Auth(browser); // a second attach wraps nothing again
		await browser.newContext({ proxy: { ...SOCKS }, locale: "en-US" });
		expect(calls).toEqual([
			{ proxy: { server: "socks5://127.0.0.1:1080" }, locale: "en-US" },
		]);
		expect(scripts.map(jugglerReads)).toEqual([AUTH]);
	});

	it.each([
		[undefined],
		[{ proxy: { server: "http://h:1", username: "u", password: "p" } }],
	])("adds no script for %j", async (options) => {
		const { browser, calls, scripts } = fakeBrowser();
		utils.attachSocks5Auth(browser);
		await browser.newContext(options);
		expect(calls).toEqual([options]);
		expect(scripts).toEqual([]);
	});
});
