/**
 * NewContext places a context behind a proxy where the proxy exits.
 * Twin of python/tests/test_proxy_geo.py: the lookup must go through the
 * proxy as Playwright would reach it (a scheme-less server is http), a failed
 * lookup must raise rather than leave the context on the host's values, and
 * the locale and position move with the clock. The lookup is camoucore's
 * proxyExitGeo, tested there.
 * Also the twin of test_new_context_version.py: the context's UA names the
 * browser's Firefox version.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

// The lookup itself is camoucore's, tested there; this file covers what
// camoufox hands it and what it does with the answer.
const lookup = vi.hoisted(() => ({
	proxies: [] as string[],
	respond: async (): Promise<unknown> => ({}),
}));

vi.mock("camoucore/ip.js", async (importOriginal) => ({
	...(await importOriginal<typeof import("camoucore/ip.js")>()),
	proxyExitGeo: async (proxy: string) => {
		lookup.proxies.push(proxy);
		return lookup.respond();
	},
}));

const { NewContext } = await import("../src/sync_api.js");
const { InvalidIP } = await import("../src/exceptions.js");
const { getRandomPreset } = await import("../src/fingerprints.js");

const EXIT = {
	ip: "203.0.113.7",
	timezone: "Europe/Paris",
	country: "FR",
	latitude: 48.8566,
	longitude: 2.3522,
};

function fakeBrowser(version = "152.0.4") {
	const calls: { options?: any; script?: string } = {};
	const browser = {
		// Playwright's Browser.version() for Firefox: MOZ_APP_VERSION_DISPLAY.
		version: () => version,
		newContext: async (options: any) => {
			calls.options = options;
			return {
				addInitScript: async (script: string) => {
					calls.script = script;
				},
			};
		},
	};
	return { browser: browser as any, calls };
}

beforeEach(() => {
	lookup.proxies.length = 0;
	lookup.respond = async () => EXIT;
});

describe("NewContext proxy lookup", () => {
	it.each([
		["1.2.3.4:8080", "http://u:p@1.2.3.4:8080"],
		["proxy.example.com:8080", "http://u:p@proxy.example.com:8080"],
		["http://proxy.example.com:8080", "http://u:p@proxy.example.com:8080"],
		["socks5://proxy.example.com:1080", "socks5://u:p@proxy.example.com:1080"],
	])("%s is looked up through %s", async (server, expected) => {
		const { browser, calls } = fakeBrowser();
		await NewContext(browser, {
			os: "linux",
			proxy: { server, username: "u", password: "p" },
		});
		expect(lookup.proxies).toEqual([expected]);
		expect(calls.options.timezoneId).toBe("Europe/Paris");
		expect(calls.script).toContain("203.0.113.7");
	});

	it("credentials with URL delimiters survive the proxy URL", async () => {
		// A raw `#`, `/` or `?` stops the URL parsing, and a raw `%41` would be
		// decoded into a different password (#823).
		const username = "us@r name";
		const password = "p#ss/w?rd:%41";
		const { browser } = fakeBrowser();
		await NewContext(browser, {
			os: "linux",
			proxy: { server: "proxy.example.com:8080", username, password },
		});
		const url = new URL(lookup.proxies[0]);
		expect([url.hostname, url.port]).toEqual(["proxy.example.com", "8080"]);
		expect(decodeURIComponent(url.username)).toBe(username);
		expect(decodeURIComponent(url.password)).toBe(password);
	});

	it("a failed lookup raises instead of launching without the values", async () => {
		lookup.respond = async () => {
			throw new InvalidIP("proxy refused");
		};
		const { browser, calls } = fakeBrowser();
		await expect(
			NewContext(browser, { os: "linux", proxy: { server: "1.2.3.4:8080" } }),
		).rejects.toThrow(InvalidIP);
		expect(calls.options).toBeUndefined();
	});

	it("moves the locale and position with the clock", async () => {
		const { browser, calls } = fakeBrowser();
		await NewContext(browser, {
			os: "linux",
			proxy: { server: "1.2.3.4:8080" },
		});
		expect(calls.options.timezoneId).toBe("Europe/Paris");
		expect(calls.options.locale).toMatch(/-FR$/);
		expect(calls.options.geolocation).toEqual({
			latitude: 48.8566,
			longitude: 2.3522,
		});
		expect(calls.options.permissions).toEqual(["geolocation"]);
	});

	it("keeps the values the caller gave", async () => {
		const position = { latitude: 51.5072, longitude: -0.1276 };
		const { browser, calls } = fakeBrowser();
		await NewContext(browser, {
			os: "linux",
			proxy: { server: "1.2.3.4:8080" },
			locale: "en-GB",
			geolocation: position,
		} as any);
		expect(calls.options.locale).toBe("en-GB");
		expect(calls.options.geolocation).toEqual(position);
		expect(calls.options.timezoneId).toBe("Europe/Paris");
		expect(calls.script).toContain("203.0.113.7");
	});

	it("skips the lookup when every value is given", async () => {
		const { browser } = fakeBrowser();
		await NewContext(browser, {
			os: "linux",
			proxy: { server: "1.2.3.4:8080" },
			webrtc_ip: "198.51.100.1",
			timezoneId: "UTC",
			locale: "en-US",
			geolocation: { latitude: 40.7128, longitude: -74.006 },
		} as any);
		expect(lookup.proxies).toEqual([]);
	});
});

describe("NewContext identity", () => {
	it("the user agent carries the browser's Firefox version", async () => {
		const { browser, calls } = fakeBrowser("160.0.1");
		await NewContext(browser, { os: "linux" });
		const userAgent = /setNavigatorUserAgent\("([^"]+)"\)/.exec(
			calls.script ?? "",
		)?.[1];
		expect(userAgent).toContain("Firefox/160.0");
		expect(userAgent).toContain("rv:160.0");
	});

	it("hands Playwright the identity under its own option names", async () => {
		// Re-casing these turned userAgent into `useragent`, which Playwright
		// drops: the HTTP User-Agent then disagreed with navigator.userAgent.
		const { browser, calls } = fakeBrowser();
		// The v150 presets all carry a DPR; the older bundle's do not.
		const preset = getRandomPreset("windows", "152");
		expect(preset?.screen?.devicePixelRatio).toBeGreaterThan(0);
		await NewContext(browser, { preset, timezoneId: "Asia/Tokyo" } as any);
		const userAgent = /setNavigatorUserAgent\("([^"]+)"\)/.exec(
			calls.script ?? "",
		)?.[1];
		expect(calls.options.userAgent).toBe(userAgent);
		expect(calls.options.deviceScaleFactor).toBeGreaterThan(0);
		expect(calls.options.viewport.width).toBeGreaterThan(0);
		expect(calls.options.timezoneId).toBe("Asia/Tokyo");
		for (const key of Object.keys(calls.options))
			expect(key, "a key Playwright does not know").not.toMatch(
				/^(useragent|devicescalefactor|timezoneid)$/,
			);
	});
});
