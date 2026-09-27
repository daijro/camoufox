/**
 * Host display geometry, in the units Firefox lays its windows out in.
 *
 * TypeScript twin of pythonlib/camoufox/display.py.
 *
 * Firefox sizes windows in **CSS pixels**. Python uses `screeninfo`, which
 * marks the process per-monitor DPI aware and therefore reports **physical**
 * pixels; where Windows display scaling is enabled the two differ by the scale
 * factor (a 1920x1080 panel at 150% is only 1280x720 CSS px), so deriving a
 * window size from the physical numbers opens it partly off-screen
 * (daijro/camoufox#425).
 *
 * There is no dependency-free `screeninfo` equivalent on npm, so the probes
 * below shell out per platform and are deliberately best-effort: any failure
 * returns null, exactly as the Python twin does when enumeration fails, and
 * the caller simply skips the screen constraint.
 *
 * X11 (xrandr) and macOS already report CSS pixels; only Windows needs the
 * scale correction, and there the DPI-aware value is what PowerShell reports.
 */
import { execFileSync } from "node:child_process";
import { OS_NAME } from "./pkgman.js";

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
