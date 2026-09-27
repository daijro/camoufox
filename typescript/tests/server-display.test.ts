/**
 * Ports of pythonlib/tests/test_server.py (the parts that apply: TS calls
 * playwright-core's launchServer in-process, so there is no launchServer.js
 * child to reap) and test_display.py's has_display().
 */
import { describe, expect, it } from "vitest";
import { hasDisplay } from "../src/display.js";
import { OS_NAME } from "../src/pkgman.js";
import { launchServer, toCamelCaseDict } from "../src/server.js";
import { camelCase } from "../src/sync_api.js";

describe("launchServer", () => {
	it.each([
		"persistent_context",
		"user_data_dir",
	])("rejects %s: a persistent context cannot be served", async (option) => {
		await expect(
			launchServer({
				[option]: option === "user_data_dir" ? "/tmp/profile" : true,
			}),
		).rejects.toThrow(/does not support/);
	});

	it("camelCases option keys the way server.camel_case does", () => {
		expect(camelCase("ws_path")).toBe("wsPath");
		expect(camelCase("firefox_user_prefs")).toBe("firefoxUserPrefs");
		expect(camelCase("_private_key")).toBe("_privateKey");
		expect(camelCase("x")).toBe("x");
		expect(
			toCamelCaseDict({ ws_path: "/a", port: 1, executablePath: "/b" }),
		).toEqual({
			wsPath: "/a",
			port: 1,
			executablePath: "/b",
		});
	});
});

describe("hasDisplay", () => {
	it.runIf(OS_NAME !== "lin")("is always true off Linux", () => {
		expect(hasDisplay({})).toBe(true);
	});

	it.runIf(OS_NAME === "lin")("needs a session on Linux", () => {
		expect(hasDisplay({})).toBe(false);
		expect(hasDisplay({ DISPLAY: ":0" })).toBe(true);
		expect(hasDisplay({ WAYLAND_DISPLAY: "wayland-0" })).toBe(true);
		expect(hasDisplay({ DISPLAY: "" })).toBe(false);
	});
});
