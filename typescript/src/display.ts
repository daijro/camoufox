/**
 * Host display geometry in CSS pixels, the unit Firefox sizes windows in: a
 * physical-pixel size opens a scaled Windows window off-screen (#425). Twin of
 * display.py; a failed probe returns null, and the screen constraint is skipped.
 */
import { execFileSync } from "node:child_process";
import { OS_NAME } from "./paths.js";

/** Size of a monitor in CSS pixels. */
export interface DisplaySize {
	width: number;
	height: number;
}

/**
 * Whether the host has a desktop session for Camoufox's window to open on.
 *
 * DISPLAY / WAYLAND_DISPLAY only ever exist on Linux, so they cannot be the
 * sole probe: keying off DISPLAY alone skips the screen constraints entirely on
 * Windows and macOS, where a session is always present.
 */
export function hasDisplay(
	env: Record<string, string | number | boolean | undefined>,
): boolean {
	if (OS_NAME !== "lin") {
		return true;
	}
	return Boolean(env.DISPLAY || env.WAYLAND_DISPLAY);
}

function run(command: string, args: string[]): string | null {
	try {
		return execFileSync(command, args, {
			encoding: "utf-8",
			stdio: ["ignore", "pipe", "ignore"],
			timeout: 5000,
		});
	} catch {
		return null;
	}
}

/** Every connected monitor's resolution, or [] when it can't be probed. */
function enumerateMonitors(): DisplaySize[] {
	if (OS_NAME === "lin") return enumerateLinux();
	if (OS_NAME === "mac") return enumerateMac();
	return enumerateWindows();
}

function enumerateLinux(): DisplaySize[] {
	// `xrandr --current` avoids a mode probe and is safe to call repeatedly.
	// Connected outputs carry a "<w>x<h>+<x>+<y>" geometry token.
	const out = run("xrandr", ["--current"]);
	if (!out) return [];
	const monitors: DisplaySize[] = [];
	for (const line of out.split("\n")) {
		if (!/\bconnected\b/.test(line)) continue;
		const match = line.match(/\b(\d+)x(\d+)\+\d+\+\d+/);
		if (!match) continue;
		monitors.push({
			width: Number.parseInt(match[1], 10),
			height: Number.parseInt(match[2], 10),
		});
	}
	return monitors;
}

function enumerateMac(): DisplaySize[] {
	const out = run("system_profiler", ["-json", "SPDisplaysDataType"]);
	if (!out) return [];
	try {
		const data = JSON.parse(out);
		const monitors: DisplaySize[] = [];
		for (const gpu of data.SPDisplaysDataType ?? []) {
			for (const display of gpu.spdisplays_ndrvs ?? []) {
				// e.g. "2560 x 1440" or "2560 x 1440 @ 60.00Hz"
				const raw: string =
					display._spdisplays_resolution ?? display.spdisplays_resolution ?? "";
				const match = raw.match(/(\d+)\s*x\s*(\d+)/);
				if (!match) continue;
				monitors.push({
					width: Number.parseInt(match[1], 10),
					height: Number.parseInt(match[2], 10),
				});
			}
		}
		return monitors;
	} catch {
		return [];
	}
}

function enumerateWindows(): DisplaySize[] {
	// Screen.AllScreens reports DPI-*unaware* bounds for a non-manifested
	// process, which is exactly the CSS-pixel figure Firefox lays out in --
	// so unlike the Python twin no scale-factor correction is needed here.
	const script =
		"Add-Type -AssemblyName System.Windows.Forms; " +
		"[System.Windows.Forms.Screen]::AllScreens | " +
		'ForEach-Object { "$($_.Bounds.Width)x$($_.Bounds.Height)" }';
	const out = run("powershell", ["-NoProfile", "-Command", script]);
	if (!out) return [];
	const monitors: DisplaySize[] = [];
	for (const line of out.split("\n")) {
		const match = line.trim().match(/^(\d+)x(\d+)$/);
		if (!match) continue;
		monitors.push({
			width: Number.parseInt(match[1], 10),
			height: Number.parseInt(match[2], 10),
		});
	}
	return monitors;
}

/**
 * Size of the roomiest attached monitor in CSS pixels, or null when the display
 * cannot be probed (no monitors, or enumeration failed).
 */
export function largestDisplay(): DisplaySize | null {
	let monitors: DisplaySize[];
	try {
		monitors = enumerateMonitors();
	} catch {
		return null;
	}
	if (!monitors.length) return null;

	// max() keeps the FIRST of equally large monitors, as Python's max() does.
	const monitor = monitors.reduce((prev, curr) =>
		curr.width * curr.height > prev.width * prev.height ? curr : prev,
	);
	return {
		width: Math.max(1, Math.trunc(monitor.width)),
		height: Math.max(1, Math.trunc(monitor.height)),
	};
}
