/**
 * NewContext derives the WebRTC IP and timezone from the proxy's exit IP.
 * Twin of pythonlib/tests/test_proxy_geo.py: the lookup must go through the
 * proxy as Playwright would reach it (a scheme-less server is http), and a
 * failed lookup must raise rather than leave the context on the host's values.
 * Also the twin of test_new_context_version.py: the context's UA names the
 * browser's Firefox version.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const impit = vi.hoisted(() => ({
	proxyUrls: [] as (string | undefined)[],
	respond: async (): Promise<unknown> => ({}),
}));

vi.mock("impit", () => ({
	Impit: class {
		// ip.ts caches one client per proxy URL, so record each request.
		constructor(private options: { proxyUrl?: string }) {}
		async fetch() {
			impit.proxyUrls.push(this.options.proxyUrl);
			const body = await impit.respond();
			return { ok: true, status: 200, json: async () => body };
		}
	},
}));

const { NewContext } = await import("../src/sync_api.js");
const { InvalidIP } = await import("../src/exceptions.js");
const { getRandomPreset } = await import("../src/fingerprints.js");

const EXIT = {
	status: "success",
	query: "203.0.113.7",
	timezone: "Europe/Paris",
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
	impit.proxyUrls.length = 0;
	impit.respond = async () => EXIT;
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
		expect(impit.proxyUrls).toContain(expected);
		expect(calls.options.timezoneId).toBe("Europe/Paris");
		expect(calls.script).toContain("203.0.113.7");
	});

	it.each([
		[
			"an unreachable proxy",
			async () => {
				throw new Error("proxy refused");
			},
		],
		[
			"a failed lookup",
			async () => ({ status: "fail", message: "private range" }),
		],
	])("%s raises instead of launching without the values", async (_, respond) => {
		impit.respond = respond;
		const { browser } = fakeBrowser();
		const launched = NewContext(browser, {
			os: "linux",
			proxy: { server: "1.2.3.4:8080" },
		});
		await expect(launched).rejects.toThrow(InvalidIP);
		await expect(launched).rejects.toThrow(/webrtc_ip/);
	});

	it("skips the lookup when both values are given", async () => {
		const { browser } = fakeBrowser();
		await NewContext(browser, {
			os: "linux",
			proxy: { server: "1.2.3.4:8080" },
			webrtc_ip: "198.51.100.1",
			timezoneId: "UTC",
		} as any);
		expect(impit.proxyUrls).toEqual([]);
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
