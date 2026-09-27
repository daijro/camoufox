/**
 * A minimal virtual display implementation for Linux.
 *
 * TypeScript twin of pythonlib/camoufox/virtdisplay.py.
 */
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import * as fs from "node:fs";
import {
	CannotExecuteXvfb,
	CannotFindXvfb,
	VirtualDisplayNotSupported,
} from "./exceptions.js";
import { OS_NAME } from "./pkgman.js";

/** Safe timeout for Xvfb writing the display num; prevents an infinite hang. */
const DISPLAYFD_READ_TIMEOUT_MS = 10_000;

/**
 * Xvfb screen geometry for headless="virtual".
 *
 * 1x1x24 is Camoufox's long-standing default and stays the default. The root
 * window size is not observable as a fingerprint: screen.* comes from the
 * generated fingerprint, applied per context in the browser, and
 * clampScreenToDisplay() is skipped entirely for virtual displays (see the
 * `!virtual_display` guard in utils.ts), so a 1x1 root never clamps a generated
 * screen down to 1x1.
 *
 * Override with CAMOUFOX_VIRTUAL_DISPLAY_SIZE="<width>x<height>x<depth>", e.g.
 * "1920x1080x24", for the cases that do want a real framebuffer to draw into.
 * Depth may be omitted.
 */
export const DEFAULT_SCREEN = "1x1x24";
export const SCREEN_ENV_VAR = "CAMOUFOX_VIRTUAL_DISPLAY_SIZE";

/**
 * The Composite extension, disabled by default (Xvfb's `-extension COMPOSITE`).
 *
 * This was briefly enabled by default on the theory that #93 (no video under
 * headless="virtual") was caused by disabling it. It was not: #93 was a juggler
 * bug, fixed by capturing the screencast from the compositor instead of from
 * libwebrtc's X11 window capturer. Both states were measured before that fix:
 *
 *   composite off, record_video_dir  -> a valid .webm of 24 pure-white frames
 *   composite ON,  record_video_dir  -> browser dies with SIGSEGV, no video
 *   composite ON,  no recording      -> fine
 *
 * The segfault was inside the X11 capturer, which the browser no longer uses,
 * so enabling Composite is no longer dangerous -- but it is also no longer good
 * for anything, since recording never touches X11 window capture now. Leave it
 * off (Camoufox's long-standing default) and keep the escape hatch:
 * CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE=1 enables it.
 */
export const COMPOSITE_ENV_VAR = "CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE";

/** Screen geometry for Xvfb's -screen argument. */
function resolveScreen(): string {
	const value = (process.env[SCREEN_ENV_VAR] ?? "").trim();
	if (!value) return DEFAULT_SCREEN;
	const parts = value.toLowerCase().split("x");
	const valid =
		(parts.length === 2 || parts.length === 3) &&
		parts.every((p) => /^\d+$/.test(p) && Number.parseInt(p, 10) > 0);
	if (!valid) {
		throw new VirtualDisplayNotSupported(
			`${SCREEN_ENV_VAR} must look like '1920x1080' or '1920x1080x24', got '${value}'`,
		);
	}
	if (parts.length === 2) parts.push("24");
	return parts.join("x");
}

export class VirtualDisplay {
	debug: boolean;
	screen: string;
	composite: boolean;
	proc: ChildProcess | null = null;
	private _display: number | null = null;

	constructor(debug: boolean = false, screen?: string, composite?: boolean) {
		this.debug = debug;
		this.screen = screen || resolveScreen();
		this.composite =
			composite ??
			["1", "true"].includes((process.env[COMPOSITE_ENV_VAR] ?? "0").trim());
	}

	get xvfbArgs(): string[] {
		return [
			"-screen",
			"0",
			this.screen,
			"-ac",
			"-nolisten",
			"tcp",
			"-extension",
			"RENDER",
			"+extension",
			"GLX",
			this.composite ? "+extension" : "-extension",
			"COMPOSITE",
			"-extension",
			"XVideo",
			"-extension",
			"XVideo-MotionCompensation",
			"-extension",
			"XINERAMA",
			"-fp",
			"built-ins",
			"-nocursor",
			"-br",
		];
	}

	get xvfbPath(): string {
		let resolved: string;
		try {
			resolved = execFileSync("which", ["Xvfb"], {
				encoding: "utf-8",
				stdio: ["ignore", "pipe", "ignore"],
			}).trim();
		} catch {
			throw new CannotFindXvfb("Please install Xvfb to use headless mode.");
		}
		if (!resolved) {
			throw new CannotFindXvfb("Please install Xvfb to use headless mode.");
		}
		try {
			fs.accessSync(resolved, fs.constants.X_OK);
		} catch {
			throw new CannotExecuteXvfb(
				`I do not have permission to execute Xvfb: ${resolved}`,
			);
		}
		return resolved;
	}

	/**
	 * Spawn Xvfb (if it isn't already running) and return its ":N" display.
	 *
	 * Uses `-displayfd` so Xvfb itself picks a free display number atomically
	 * and reports it back, avoiding userspace races. Python's `pass_fds` keeps
	 * the fd at its parent number; Node's `stdio` array renumbers extra pipes
	 * from 3 upward, so we hand Xvfb fd 3 and read the pipe at index 3.
	 */
	async get(): Promise<string> {
		VirtualDisplay.assertLinux();

		if (this.proc === null) {
			const cmd = [this.xvfbPath, "-displayfd", "3", ...this.xvfbArgs];
			if (this.debug) {
				console.log("Starting virtual display:", cmd.join(" "));
			}
			this.proc = spawn(cmd[0], cmd.slice(1), {
				stdio: [
					"ignore",
					this.debug ? "inherit" : "ignore",
					this.debug ? "inherit" : "ignore",
					"pipe",
				],
				detached: true,
				env: {
					...process.env,
					// Force Mesa software GLX; we don't use the GPU anyway.
					__GLX_VENDOR_LIBRARY_NAME: "mesa",
					LIBGL_ALWAYS_SOFTWARE: "1",
				},
			});

			// A spawn that fails after spawn() returns (EACCES, ENOEXEC, a noexec
			// mount) is an 'error' event on the child; with no listener Node
			// treats it as uncaught and exits. readDisplayNumber() turns it into
			// CannotExecuteXvfb; this keeps any later one from killing the process.
			this.proc.on("error", () => {});

			const displayFd = this.proc.stdio[3] as NodeJS.ReadableStream | null;
			if (!displayFd) {
				this.kill();
				throw new CannotExecuteXvfb("Could not open Xvfb's -displayfd pipe");
			}

			const raw = await this.readDisplayNumber(displayFd);
			const parsed = Number.parseInt(raw.trim(), 10);
			if (Number.isNaN(parsed)) {
				this.kill();
				throw new CannotExecuteXvfb(`Xvfb wrote non-integer display: '${raw}'`);
			}
			this._display = parsed;
		} else if (this.debug) {
			console.log(`Using virtual display: ${this._display}`);
		}

		return `:${this._display}`;
	}

	private readDisplayNumber(stream: NodeJS.ReadableStream): Promise<string> {
		return new Promise<string>((resolve, reject) => {
			let buf = "";
			let settled = false;

			const finish = (fn: () => void) => {
				if (settled) return;
				settled = true;
				clearTimeout(timer);
				stream.removeAllListeners("data");
				stream.removeAllListeners("end");
				stream.removeAllListeners("error");
				stream.on("error", () => {}); // a late pipe error is not fatal
				proc?.removeListener("error", onSpawnError);
				fn();
			};

			const proc = this.proc;
			const onSpawnError = (error: Error) =>
				finish(() => {
					this.kill();
					reject(new CannotExecuteXvfb(`Could not start Xvfb: ${error}`));
				});
			proc?.once("error", onSpawnError);

			const timer = setTimeout(() => {
				finish(() => {
					this.kill();
					reject(
						new CannotExecuteXvfb(
							`Xvfb did not report a display within ${DISPLAYFD_READ_TIMEOUT_MS}ms`,
						),
					);
				});
			}, DISPLAYFD_READ_TIMEOUT_MS);

			stream.on("data", (chunk) => {
				buf += chunk.toString();
				if (buf.includes("\n")) {
					finish(() => resolve(buf));
				}
			});
			stream.on("end", () => {
				finish(() => {
					if (buf.includes("\n")) {
						resolve(buf);
						return;
					}
					const exit = this.proc?.exitCode;
					this.kill();
					reject(
						new CannotExecuteXvfb(
							`Xvfb did not report a display (got '${buf}', exit=${exit})`,
						),
					);
				});
			});
			stream.on("error", (error) => {
				finish(() => {
					this.kill();
					reject(
						new CannotExecuteXvfb(`Failed to read Xvfb's display: ${error}`),
					);
				});
			});
		});
	}

	/**
	 * Stop Xvfb if it is running, and remove its lock and socket either way.
	 *
	 * The cleanup deliberately does NOT depend on whether we did the killing.
	 * It used to: the whole body sat behind "is the process still running", so
	 * a display whose Xvfb had already died -- crashed, OOM-killed, or reaped
	 * with the browser's process group -- was never cleaned up at all.
	 *
	 * That is backwards. A SIGKILLed Xvfb never gets to remove its own socket,
	 * so the crash path is precisely the one where /tmp/.X11-unix/X<n> is left
	 * behind. Those accumulate, and because -displayfd scans upward for a free
	 * number, every stranded socket pushes the next display higher until a
	 * long-running host stops being able to allocate one.
	 *
	 * Python waits for the killed process before unlinking; kill() is
	 * synchronous here, but a SIGKILLed Xvfb can no longer recreate either
	 * file, so unlinking right after the signal leaves the same end state.
	 */
	kill(): void {
		if (!this.proc) return;

		if (this.proc.exitCode === null && this.proc.signalCode === null) {
			if (this.debug) {
				console.log("Terminating virtual display:", this._display);
			}
			try {
				this.proc.kill("SIGKILL");
			} catch {
				// Already gone.
			}
		} else if (this.debug) {
			console.log("Virtual display already exited:", this._display);
		}

		for (const stale of [
			`/tmp/.X${this._display}-lock`,
			`/tmp/.X11-unix/X${this._display}`,
		]) {
			try {
				fs.unlinkSync(stale);
			} catch {
				// Missing is the normal case; anything else (a permission error
				// from a number another user has since claimed) must not take
				// down a teardown path.
			}
		}

		this.proc = null;
	}

	static assertLinux(): void {
		if (OS_NAME !== "lin") {
			throw new VirtualDisplayNotSupported(
				"Virtual display is only supported on Linux.",
			);
		}
	}
}
