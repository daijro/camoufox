/**
 * headless="virtual-gpu" on a real GPU, through the TypeScript API.
 *
 * Opt-in, like e2e.test.ts: it needs the card CAMOUFOX_GPU names, Xorg with
 * the card's driver and, without root, the machine set up for it
 * (`npx camoufox gpu-setup <gpu> | sudo sh`). CI has no GPU runner.
 *
 *   CAMOUFOX_GPU=01:00.0 CAMOUFOX_EXECUTABLE=/path/to/camoufox-bin pnpm test tests/gpu-display.test.ts
 *
 * Twin of browser/tests/native/test_gpu_display.py. The GPU-free half is
 * gpudisplay.test.ts.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import { firefox } from "playwright-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { gpuVendor, selectGpu } from "../src/gpudisplay.js";
import { launchServer } from "../src/server.js";
import { Camoufox } from "../src/sync_api.js";

const ENABLED = Boolean(process.env.CAMOUFOX_GPU?.trim());
const EXECUTABLE = process.env.CAMOUFOX_EXECUTABLE ?? "";
const ACTIVE_VT = "/sys/class/tty/tty0/active";

const READ_GPU = () => {
	const gl = (globalThis as any).document
		.createElement("canvas")
		.getContext("webgl");
	const info = gl.getExtension("WEBGL_debug_renderer_info");
	return `${gl.getParameter(info.UNMASKED_VENDOR_WEBGL)} ${gl.getParameter(info.UNMASKED_RENDERER_WEBGL)}`;
};

function xorgServers(): Set<number> {
	try {
		return new Set(
			execFileSync("pgrep", ["-x", "Xorg"], { encoding: "utf-8" })
				.split(/\s+/)
				.filter(Boolean)
				.map(Number),
		);
	} catch {
		return new Set();
	}
}

async function waitUntilGone(pids: Set<number>): Promise<number[]> {
	const deadline = Date.now() + 15_000;
	let left = [...pids].filter((pid) => xorgServers().has(pid));
	while (left.length && Date.now() < deadline) {
		await new Promise((r) => setTimeout(r, 100));
		left = [...pids].filter((pid) => xorgServers().has(pid));
	}
	return left;
}

describe.runIf(ENABLED)("headless='virtual-gpu' on a real GPU", () => {
	if (ENABLED && !EXECUTABLE) {
		throw new Error("CAMOUFOX_EXECUTABLE must name the browser to test");
	}
	const vendor = () => gpuVendor(selectGpu()).toLowerCase();
	let vt: string | null = null;
	let wayland: string | undefined;

	beforeEach(() => {
		// Nothing here may open on the desktop the tests run from.
		wayland = process.env.WAYLAND_DISPLAY;
		delete process.env.WAYLAND_DISPLAY;
		vt = fs.existsSync(ACTIVE_VT)
			? fs.readFileSync(ACTIVE_VT, "utf-8").trim()
			: null;
	});
	afterEach(() => {
		if (wayland !== undefined) process.env.WAYLAND_DISPLAY = wayland;
		if (vt) expect(fs.readFileSync(ACTIVE_VT, "utf-8").trim()).toBe(vt);
	});

	it("renders on the named card and leaves no server behind", async () => {
		const before = xorgServers();
		const browser = await Camoufox({
			headless: "virtual-gpu",
			os: "linux",
			executable_path: EXECUTABLE,
		});
		const started = new Set(
			[...xorgServers()].filter((pid) => !before.has(pid)),
		);
		try {
			expect(started.size).toBe(1);
			const display = (browser as any)._virtualDisplay;
			expect(display.usesGpu()).toBe(true);
			// The identity claims the card that renders, not the desktop's GPU.
			const page = await browser.newPage();
			expect((await page.evaluate(READ_GPU)).toLowerCase()).toContain(vendor());
		} finally {
			await browser.close();
		}
		expect(await waitUntilGone(started)).toEqual([]);
	}, 120_000);

	it("serves a browser on the card", async () => {
		const before = xorgServers();
		const server = await launchServer({
			headless: "virtual-gpu",
			os: "linux",
			executable_path: EXECUTABLE,
		});
		const started = new Set(
			[...xorgServers()].filter((pid) => !before.has(pid)),
		);
		try {
			expect(started.size).toBe(1);
			const browser = await firefox.connect(server.wsEndpoint());
			try {
				const page = await browser.newPage();
				expect((await page.evaluate(READ_GPU)).toLowerCase()).toContain(
					vendor(),
				);
			} finally {
				await browser.close();
			}
		} finally {
			await server.close();
		}
		expect(await waitUntilGone(started)).toEqual([]);
	}, 120_000);
});
