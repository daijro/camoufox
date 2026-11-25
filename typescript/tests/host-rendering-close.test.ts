/**
 * The host GPU probe's browser.close shares the probe's one deadline:
 * python/src/camoufox/host_rendering.py bounds the whole probe with a single
 * communicate() timeout.
 */
import { firefox } from "playwright-core";
import { afterEach, expect, it, vi } from "vitest";
import { HOST_GPU_PROBE_TIMEOUT_MS, hostGpu } from "../src/host_rendering.js";

const HOST_GPU: [string, string] = [
	"AMD",
	"Radeon HD 3200 Graphics, or similar",
];

afterEach(() => vi.restoreAllMocks());

it("a good reading survives a browser.close slower than a second", async () => {
	vi.useFakeTimers();
	try {
		vi.spyOn(firefox, "launch").mockResolvedValue({
			newPage: async () => ({ evaluate: async () => HOST_GPU }),
			close: () => new Promise<void>((resolve) => setTimeout(resolve, 1_500)),
		} as any);
		const pending = hostGpu("/nonexistent/slow-close-camoufox", true, {}, {});
		const resolved = expect(pending).resolves.toEqual(HOST_GPU);

		await vi.advanceTimersByTimeAsync(1_500);
		await resolved;
	} finally {
		vi.useRealTimers();
	}
});

it("a browser.close that never returns fails at the shared deadline", async () => {
	vi.useFakeTimers();
	try {
		vi.spyOn(firefox, "launch").mockResolvedValue({
			newPage: async () => ({ evaluate: async () => HOST_GPU }),
			close: () => new Promise<void>(() => undefined),
		} as any);
		const pending = hostGpu("/nonexistent/stuck-close-camoufox", true, {}, {});
		const rejected = expect(pending).rejects.toThrow(
			"Host GPU probe timed out after 30000 ms",
		);

		await vi.advanceTimersByTimeAsync(HOST_GPU_PROBE_TIMEOUT_MS - 1);
		await vi.advanceTimersByTimeAsync(1);
		await rejected;
	} finally {
		vi.useRealTimers();
	}
});
