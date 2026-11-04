/**
 * headless: true on Linux runs headed on a private Xvfb whenever Xvfb is there
 * (python/tests/test_headless_mode.py). Firefox's own -headless shows stand-in
 * system colors and fonts and a frameless window, which pages read.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import * as utils from "../src/utils.js";
import { VirtualDisplay } from "../src/virtdisplay.js";

const deps = utils.utilsDeps as any;
const saved = { osName: deps.osName, xvfbMissing: deps.xvfbMissing };

afterEach(() => {
	Object.assign(deps, saved);
	vi.restoreAllMocks();
});

function host(os: string, missing?: string) {
	deps.osName = () => os;
	deps.xvfbMissing = () => missing;
}

describe("headless: true", () => {
	it("runs on Xvfb on Linux", async () => {
		host("lin");
		vi.spyOn(VirtualDisplay.prototype, "get").mockResolvedValue(":77");
		const options: Record<string, any> = {};
		const [display, headless] = await utils.startVirtualDisplay(
			true,
			false,
			options,
		);
		expect(display).toBeInstanceOf(VirtualDisplay);
		expect(headless).toBe(false);
		expect(options.virtual_display).toBe(":77");
	});

	it.each([
		"Xvfb (xvfb)",
		"setpriv (util-linux)",
	])("falls back to Firefox headless with a warning naming %s", async (missing) => {
		host("lin", missing);
		const emit = vi.spyOn(process, "emitWarning").mockImplementation(() => {});
		const options: Record<string, any> = {};
		const [display, headless] = await utils.startVirtualDisplay(
			true,
			false,
			options,
		);
		expect(display).toBeNull();
		expect(headless).toBe(true);
		expect(options.virtual_display).toBeUndefined();
		expect(String(emit.mock.calls[0]?.[0])).toContain(missing);
	});

	it("stays Firefox headless off Linux", () => {
		host("win");
		expect(utils.headlessMode(true)).toBe(true);
	});

	it("keeps a caller's own display", () => {
		host("lin");
		expect(utils.headlessMode(true, { virtual_display: ":5" })).toBe(true);
	});

	it.each([
		false,
		undefined,
		"virtual",
	] as const)("leaves %s alone", (value) => {
		host("lin");
		expect(utils.headlessMode(value)).toBe(value);
	});
});
