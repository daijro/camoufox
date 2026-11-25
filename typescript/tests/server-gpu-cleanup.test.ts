/**
 * launchServer with headless: "virtual-gpu" proves the GPU through its own
 * server. Whatever fails after the server is up must close it and kill the
 * display (python/src/camoufox/server.py shuts the process down on any error).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	display: undefined as unknown as { kill: ReturnType<typeof vi.fn> },
	server: undefined as unknown as {
		on: ReturnType<typeof vi.fn>;
		close: ReturnType<typeof vi.fn>;
		wsEndpoint: ReturnType<typeof vi.fn>;
	},
	browser: undefined as unknown as { close: ReturnType<typeof vi.fn> },
	connect: vi.fn(),
	proveGpu: vi.fn(),
}));

vi.mock("playwright-core", () => ({
	firefox: {
		launchServer: async () => mocks.server,
		connect: mocks.connect,
	},
}));
vi.mock("../src/gpudisplay.js", () => ({
	GpuDisplay: class {},
	proveGpu: mocks.proveGpu,
}));
vi.mock("../src/cpu_affinity.js", () => ({
	withUnpinnedLaunch: <T>(fn: () => T) => fn(),
}));
vi.mock("../src/utils.js", async () => {
	const { GpuDisplay } = await import("../src/gpudisplay.js");
	return {
		launchOptions: async () => ({}),
		startVirtualDisplay: async () => [
			Object.assign(new GpuDisplay(), mocks.display),
			false,
		],
	};
});

const { launchServer } = await import("../src/server.js");

beforeEach(() => {
	mocks.display = { kill: vi.fn() };
	mocks.server = {
		on: vi.fn(),
		close: vi.fn(async () => {}),
		wsEndpoint: vi.fn(() => "ws://127.0.0.1:1/x"),
	};
	mocks.browser = { close: vi.fn(async () => {}) };
	mocks.connect.mockReset().mockResolvedValue(mocks.browser);
	mocks.proveGpu.mockReset().mockResolvedValue(undefined);
});

describe("launchServer GPU proof", () => {
	it("returns the server and leaves it running when the proof passes", async () => {
		await expect(launchServer({ headless: "virtual-gpu" })).resolves.toBe(
			mocks.server,
		);
		expect(mocks.server.close).not.toHaveBeenCalled();
		expect(mocks.display.kill).not.toHaveBeenCalled();
		expect(mocks.browser.close).toHaveBeenCalledOnce();
	});

	it("closes the server and kills the display when the connect fails", async () => {
		const failure = new Error("connect refused");
		mocks.connect.mockRejectedValue(failure);
		await expect(launchServer({ headless: "virtual-gpu" })).rejects.toBe(
			failure,
		);
		expect(mocks.server.close).toHaveBeenCalledOnce();
		expect(mocks.display.kill).toHaveBeenCalledOnce();
	});

	it("closes the server and kills the display when the proof fails", async () => {
		const failure = new Error("software renderer");
		mocks.proveGpu.mockRejectedValue(failure);
		await expect(launchServer({ headless: "virtual-gpu" })).rejects.toBe(
			failure,
		);
		expect(mocks.server.close).toHaveBeenCalledOnce();
		expect(mocks.display.kill).toHaveBeenCalledOnce();
		expect(mocks.browser.close).toHaveBeenCalledOnce();
	});
});
