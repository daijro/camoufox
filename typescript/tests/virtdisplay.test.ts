/**
 * Mirrors pythonlib/tests/test_virtdisplay.py: the screen-geometry
 * resolution and the Xvfb argument vector (no X server needed), plus the real
 * Xvfb lifecycle when Xvfb is installed (Linux only).
 *
 * VIRTDISPLAY_TEST_N controls the concurrent-launch count (default 50).
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
	CannotExecuteXvfb,
	VirtualDisplayNotSupported,
} from "../src/exceptions.js";
import {
	COMPOSITE_ENV_VAR,
	DEFAULT_SCREEN,
	SCREEN_ENV_VAR,
	VirtualDisplay,
} from "../src/virtdisplay.js";
import { prerequisite } from "./prereq.js";

afterEach(() => {
	delete process.env[SCREEN_ENV_VAR];
	delete process.env[COMPOSITE_ENV_VAR];
});

describe("screen geometry", () => {
	it("defaults to 1x1x24", () => {
		expect(new VirtualDisplay().screen).toBe(DEFAULT_SCREEN);
		expect(DEFAULT_SCREEN).toBe("1x1x24");
	});

	it("accepts an explicit constructor override", () => {
		expect(new VirtualDisplay(false, "800x600x16").screen).toBe("800x600x16");
	});

	it("reads WxH from the env var and appends a depth of 24", () => {
		process.env[SCREEN_ENV_VAR] = "1920x1080";
		expect(new VirtualDisplay().screen).toBe("1920x1080x24");
	});

	it("reads WxHxD from the env var verbatim", () => {
		process.env[SCREEN_ENV_VAR] = "1920x1080x16";
		expect(new VirtualDisplay().screen).toBe("1920x1080x16");
	});

	it("falls back to the default for an empty env var", () => {
		process.env[SCREEN_ENV_VAR] = "   ";
		expect(new VirtualDisplay().screen).toBe(DEFAULT_SCREEN);
	});

	it("rejects malformed geometry rather than handing Xvfb junk", () => {
		for (const bad of ["1920", "1920x", "axb", "1920x1080x24x8", "0x1080"]) {
			process.env[SCREEN_ENV_VAR] = bad;
			expect(() => new VirtualDisplay()).toThrow(VirtualDisplayNotSupported);
		}
	});
});

describe("xvfbArgs", () => {
	it("passes the resolved screen through to -screen 0", () => {
		const args = new VirtualDisplay(false, "1280x720x24").xvfbArgs;
		const idx = args.indexOf("-screen");
		expect(idx).toBeGreaterThanOrEqual(0);
		expect(args[idx + 1]).toBe("0");
		expect(args[idx + 2]).toBe("1280x720x24");
	});

	it("disables COMPOSITE by default", () => {
		const args = new VirtualDisplay().xvfbArgs;
		expect(args[args.indexOf("COMPOSITE") - 1]).toBe("-extension");
	});

	it("enables COMPOSITE via the env escape hatch", () => {
		process.env[COMPOSITE_ENV_VAR] = "1";
		const args = new VirtualDisplay().xvfbArgs;
		expect(args[args.indexOf("COMPOSITE") - 1]).toBe("+extension");
	});

	it("enables COMPOSITE via the constructor", () => {
		const args = new VirtualDisplay(false, undefined, true).xvfbArgs;
		expect(args[args.indexOf("COMPOSITE") - 1]).toBe("+extension");
	});

	it("keeps GLX on and the cursor off", () => {
		const args = new VirtualDisplay().xvfbArgs;
		expect(args[args.indexOf("GLX") - 1]).toBe("+extension");
		expect(args).toContain("-nocursor");
		expect(args).toContain("-nolisten");
	});
});

describe("kill", () => {
	it("is safe to call on a display that was never started", () => {
		expect(() => new VirtualDisplay().kill()).not.toThrow();
	});
});

function hasXvfb(): boolean {
	if (process.platform !== "linux") return false;
	try {
		execFileSync("which", ["Xvfb"], { stdio: "ignore" });
		return true;
	} catch {
		return false;
	}
}

const DISPLAY_RE = /^:\d+$/;
const N = Number.parseInt(process.env.VIRTDISPLAY_TEST_N ?? "50", 10);

describe.skipIf(
	process.platform !== "linux" ||
		!prerequisite("xvfb", hasXvfb(), "apt-get install xvfb"),
)("Xvfb lifecycle", () => {
	const tracked: VirtualDisplay[] = [];
	const track = (vd: VirtualDisplay) => {
		tracked.push(vd);
		return vd;
	};
	afterEach(() => {
		for (const vd of tracked.splice(0)) {
			try {
				vd.kill();
			} catch {}
		}
	});

	async function waitForExit(
		proc: import("node:child_process").ChildProcess,
		timeoutMs = 5000,
	) {
		const deadline = Date.now() + timeoutMs;
		while (Date.now() < deadline) {
			if (proc.exitCode !== null || proc.signalCode !== null) return;
			await new Promise((r) => setTimeout(r, 25));
		}
	}

	it("single launch returns a valid display and kill terminates Xvfb", async () => {
		const vd = track(new VirtualDisplay());
		const display = await vd.get();
		expect(display).toMatch(DISPLAY_RE);
		const proc = vd.proc;
		expect(proc).not.toBeNull();
		expect(proc?.exitCode).toBeNull();

		vd.kill();
		expect(vd.proc).toBeNull();
		if (proc) await waitForExit(proc);
		expect(proc?.exitCode !== null || proc?.signalCode !== null).toBe(true);
	});

	it("get() is idempotent within one VirtualDisplay", async () => {
		const vd = track(new VirtualDisplay());
		expect(await vd.get()).toBe(await vd.get());
	});

	it("concurrent reservations all get unique displays", async () => {
		const vds = Array.from({ length: N }, () => track(new VirtualDisplay()));
		const displays = await Promise.all(vds.map((vd) => vd.get()));
		for (const d of displays) expect(d).toMatch(DISPLAY_RE);
		expect(new Set(displays).size).toBe(displays.length);
		for (const vd of vds) expect(vd.proc?.exitCode).toBeNull();
		const procs = vds.map((vd) => vd.proc);
		for (const vd of vds) vd.kill();
		for (const p of procs) if (p) await waitForExit(p);
		for (const p of procs) {
			expect(p?.exitCode !== null || p?.signalCode !== null).toBe(true);
		}
	}, 60_000);

	it("released display numbers can be reused on the next launch", async () => {
		const a = track(new VirtualDisplay());
		const aDisplay = await a.get();
		const aProc = a.proc;
		a.kill();
		if (aProc) await waitForExit(aProc);

		const b = track(new VirtualDisplay());
		expect(await b.get()).toMatch(DISPLAY_RE);
		b.kill();
		expect(aDisplay).toMatch(DISPLAY_RE);
	});

	it("kill() removes the lock and socket even when Xvfb already died", async () => {
		const vd = track(new VirtualDisplay());
		const display = (await vd.get()).slice(1);
		const proc = vd.proc;
		// SIGKILL behind the wrapper's back: Xvfb never gets to clean up.
		proc?.kill("SIGKILL");
		if (proc) await waitForExit(proc);
		expect(fs.existsSync(`/tmp/.X11-unix/X${display}`)).toBe(true);

		vd.kill();
		expect(vd.proc).toBeNull();
		expect(fs.existsSync(`/tmp/.X${display}-lock`)).toBe(false);
		expect(fs.existsSync(`/tmp/.X11-unix/X${display}`)).toBe(false);
	});
});

describe.runIf(process.platform === "linux")(
	"an Xvfb that cannot start",
	() => {
		it("throws CannotExecuteXvfb instead of crashing the process", async () => {
			// Bypass the xvfbPath getter's up-front checks, as a binary that changes
			// between them and the spawn would: execve then fails with EACCES after
			// spawn() returns, as an 'error' event on the child.
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-xvfb-"));
			const fake = path.join(dir, "Xvfb");
			fs.writeFileSync(fake, "#!/bin/sh\n");
			fs.chmodSync(fake, 0o644);
			const vd = new VirtualDisplay();
			Object.defineProperty(vd, "xvfbPath", { get: () => fake });
			try {
				await expect(vd.get()).rejects.toThrow(CannotExecuteXvfb);
			} finally {
				fs.rmSync(dir, { recursive: true, force: true });
			}
		});
	},
);
