/**
 * headless="virtual-gpu": a headless Xorg server pinned to one GPU.
 *
 * TypeScript twin of python/src/camoufox/gpudisplay.py.
 *
 * Xvfb has no GPU path, so a browser on it renders WebGL and canvas with
 * Mesa's software rasterizer. This display is a real Xorg server bound to one
 * card by its PCI address, drawing a virtual screen with no monitor attached,
 * so the browser renders on that card. The card is always named, never
 * guessed: the identity claims the GPU that renders, and two cards render
 * differently.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import {
	AmbiguousGpuSelection,
	CannotExecuteXorg,
	CannotFindXorg,
	GpuNotFound,
	GpuSoftwareFallback,
	GpuVtTakeover,
	NoGpuFound,
} from "./exceptions.js";
import { VirtualDisplay } from "./virtdisplay.js";
import { LeakWarning } from "./warnings.js";

/** Names the card when the `gpu` launch option is not given. */
export const GPU_ENV_VAR = "CAMOUFOX_GPU";

/**
 * How long the browser has to render on the GPU after the probe page starts
 * drawing. A card busy with other work took 5-10s in Holo's measurements.
 */
export const GPU_WAIT_S = 30;
export const GPU_WAIT_ENV_VAR = "CAMOUFOX_GPU_WAIT_S";

/**
 * The root window is not observable (screen.* is spoofed per context), but
 * the GPU compositor needs a real surface, so it is not 1x1 like Xvfb's.
 */
export const GPU_SCREEN = "1920x1080x24";

/** Where Xorg looks up a relative -config when the setuid wrapper elevates it. */
export const SYSTEM_CONFIG_DIR = "/etc/X11";

// Without root, Xorg.wrap must let any user start Xorg (a launch from ssh,
// systemd or a container is not a console login) and keep it root, which a
// server with no VT of its own needs to open the card. Stock Debian and Ubuntu
// ship allowed_users=console and needs_root_rights=auto.
export const XWRAPPER_CONFIG = "/etc/X11/Xwrapper.config";
export const XWRAPPER_SETTINGS: Readonly<Record<string, string>> = {
	allowed_users: "anybody",
	needs_root_rights: "yes",
};
export const XORG_WRAPPERS = [
	"/usr/lib/xorg/Xorg.wrap",
	"/usr/libexec/Xorg.wrap",
] as const;

/**
 * -terminate: the server exits this many seconds after its last client leaves.
 * -sharevts: never take a VT of its own, which blanks a live desktop.
 */
export const SERVER_FLAGS = [
	"-terminate",
	"2",
	"-nolisten",
	"tcp",
	"-sharevts",
	"-novtswitch",
] as const;

/**
 * Firefox's GPU paths, on by default for this display only; the caller's prefs
 * win. webgl.force-enabled is set by every launch already. Forcing the
 * accelerated canvas made 2D canvas match Windows Firefox on the same card.
 */
export const GPU_PREFS: Record<string, boolean> = {
	"gfx.webrender.all": true,
	"layers.acceleration.force-enabled": true,
	"gfx.x11-egl.enabled": true,
	"gfx.canvas.accelerated": true,
	"gfx.canvas.accelerated.force-enabled": true,
};

/**
 * Draws one WebGL frame per animation frame: Firefox opens the GPU only when
 * something renders.
 */
export const PROBE_PAGE =
	"data:text/html,<canvas id=c width=32 height=32></canvas><script>" +
	"const gl=c.getContext('webgl2')||c.getContext('webgl');" +
	"function f(){if(gl){gl.clear(gl.COLOR_BUFFER_BIT);gl.flush();}requestAnimationFrame(f);}f();" +
	"</script>";

const ACTIVE_VT = "/sys/class/tty/tty0/active";
/**
 * A crash right after startup (a driver fault under VRAM pressure) and a VT
 * switch both land just after the display is reported.
 */
const SETTLE_MS = 1000;

/** An X11 connection setup request: little-endian, protocol 11.0, no auth. */
const X11_SETUP = Buffer.from([0x6c, 0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 0]);

const VENDORS: Record<string, string> = {
	"0x10de": "NVIDIA",
	"0x1002": "AMD",
	"0x8086": "Intel",
};

const PCI_ADDRESS = /^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$/;

/** A GPU with a DRM render node, as sysfs describes it. */
export interface GpuDevice {
	pciAddress: string;
	renderNode: string;
	cardNode: string | null;
	vendorId: string;
	deviceId: string;
	kernelDriver: string;
	/** /dev/nvidia<minor> for the NVIDIA driver, which renders through it. */
	nvidiaNode: string | null;
}

export function gpuVendor(gpu: GpuDevice): string {
	return VENDORS[gpu.vendorId] ?? gpu.vendorId;
}

/** Xorg's BusID: decimal bus:device:function, without the domain. */
export function busId(gpu: GpuDevice): string {
	const [, bus, devFn] = gpu.pciAddress.split(":");
	const [dev, fn] = devFn.split(".");
	return `PCI:${Number.parseInt(bus, 16)}:${Number.parseInt(dev, 16)}:${Number.parseInt(fn, 16)}`;
}

/** modesetting drives any KMS device with glamor; NVIDIA needs its own. */
export function xorgDriver(gpu: GpuDevice): string {
	return gpu.kernelDriver === "nvidia" ? "nvidia" : "modesetting";
}

/** Whether a DRM file's usage stats (its fdinfo) show time on a GPU engine. */
/**
 * Whether a DRM file's usage stats (its fdinfo) show work on a GPU engine.
 *
 * Drivers report busy time (drm-engine-<engine>: <n> ns; amdgpu, i915) or busy
 * cycles (drm-cycles-<engine>: <n>; xe reports only these). drm-total-cycles
 * counts the GPU's clock whether this client used it or not, so it is not work.
 */
export function drewOnGpu(fdinfo: string): boolean {
	return [
		...fdinfo.matchAll(
			/^drm-(?:engine-[\w-]+:\s*(\d+) ns|cycles-[\w-]+:\s*(\d+))$/gm,
		),
	].some((match) => Number(match[1] ?? match[2]) > 0);
}

/**
 * The card's render node and its primary node. Firefox's GPU work is accounted
 * to whichever it was handed: a second launch from one process on an RX 7900
 * XTX drew through /dev/dri/card0, not renderD128.
 */
export function drmNodes(gpu: GpuDevice): string[] {
	return [gpu.renderNode, gpu.cardNode].filter((node): node is string =>
		Boolean(node),
	);
}

export function describeGpu(gpu: GpuDevice): string {
	return `${gpu.pciAddress} ${gpuVendor(gpu)} [${gpu.vendorId}:${gpu.deviceId}] driver=${gpu.kernelDriver} ${gpu.renderNode}`;
}

function read(file: string): string {
	try {
		return fs.readFileSync(file, "utf-8").trim();
	} catch {
		return "";
	}
}

function realpath(file: string): string | null {
	try {
		return fs.realpathSync(file);
	} catch {
		return null;
	}
}

function list(dir: string): string[] {
	try {
		return fs.readdirSync(dir);
	} catch {
		return [];
	}
}

function nvidiaNode(root: string, pciAddress: string): string | null {
	const info = read(
		path.join(root, "proc/driver/nvidia/gpus", pciAddress, "information"),
	);
	const match = /^Device Minor:\s*(\d+)/m.exec(info);
	return match ? `/dev/nvidia${match[1]}` : null;
}

/**
 * The GPUs with a render node and a PCI address, in PCI address order.
 *
 * Ordered by PCI address, not render node number: render nodes are numbered in
 * the order the drivers loaded, which can change from one boot to the next.
 */
export function enumerateGpus(root = "/"): GpuDevice[] {
	const drm = path.join(root, "sys/class/drm");
	const cards = new Map<string, string>();
	for (const card of list(drm)) {
		if (!/^card\d+$/.test(card)) continue;
		const real = realpath(path.join(drm, card, "device"));
		if (real) cards.set(real, `/dev/dri/${card}`);
	}

	const gpus: GpuDevice[] = [];
	for (const node of list(path.join(root, "dev/dri"))) {
		if (!node.startsWith("renderD")) continue;
		const device = path.join(drm, node, "device");
		const real = realpath(device);
		if (!real || !PCI_ADDRESS.test(path.basename(real))) continue;
		const pciAddress = path.basename(real);
		const uevent = Object.fromEntries(
			read(path.join(device, "uevent"))
				.split("\n")
				.filter((line) => line.includes("="))
				.map((line) => [
					line.slice(0, line.indexOf("=")),
					line.slice(line.indexOf("=") + 1),
				]),
		);
		const kernelDriver = uevent.DRIVER ?? "";
		gpus.push({
			pciAddress,
			renderNode: `/dev/dri/${node}`,
			cardNode: cards.get(real) ?? null,
			vendorId: read(path.join(device, "vendor")).toLowerCase(),
			deviceId: read(path.join(device, "device")).toLowerCase(),
			kernelDriver,
			nvidiaNode:
				kernelDriver === "nvidia" ? nvidiaNode(root, pciAddress) : null,
		});
	}
	return gpus.sort((a, b) =>
		a.pciAddress < b.pciAddress ? -1 : a.pciAddress > b.pciAddress ? 1 : 0,
	);
}

function matches(index: number, gpu: GpuDevice, selector: string): boolean {
	if (/^\d+$/.test(selector)) return Number(selector) === index;
	const ids = `${gpu.vendorId}:${gpu.deviceId}`.replaceAll("0x", "");
	const names = [gpu.renderNode, gpuVendor(gpu), ids];
	if (gpu.cardNode) names.push(gpu.cardNode);
	const wanted = selector.replaceAll("0x", "");
	return (
		names.some(
			(name) =>
				name.toLowerCase() === wanted ||
				path.basename(name).toLowerCase() === wanted,
		) || gpu.pciAddress.includes(selector)
	);
}

function listing(gpus: GpuDevice[], shown?: GpuDevice[]): string {
	return gpus
		.map((gpu, i) =>
			!shown || shown.includes(gpu) ? `  [${i}] ${describeGpu(gpu)}` : null,
		)
		.filter((line) => line !== null)
		.join("\n");
}

/**
 * The one GPU `selector` (or CAMOUFOX_GPU) names.
 *
 * A selector is an index into enumerateGpus(), a render or card node (name or
 * /dev/dri path), a PCI address or part of one, vendor:device ids, or a vendor
 * name. Without one, the host must have exactly one GPU.
 */
export function selectGpu(
	selector?: string | number | null,
	gpus: GpuDevice[] = enumerateGpus(),
): GpuDevice {
	if (!gpus.length) {
		throw new NoGpuFound(
			"virtual-gpu: no GPU render node with a PCI address. Is a GPU present, is its driver " +
				"loaded, and are /dev/dri and /sys visible (--device /dev/dri in a container)?",
		);
	}
	const wanted = String(selector ?? process.env[GPU_ENV_VAR] ?? "")
		.trim()
		.toLowerCase();
	if (!wanted) {
		if (gpus.length === 1) return gpus[0];
		throw new AmbiguousGpuSelection(
			`virtual-gpu: ${gpus.length} GPUs found. Name one with gpu= or ${GPU_ENV_VAR}, ` +
				`preferably by PCI address:\n${listing(gpus)}`,
		);
	}
	const matched = gpus.filter((gpu, i) => matches(i, gpu, wanted));
	if (!matched.length) {
		throw new GpuNotFound(
			`virtual-gpu: no GPU matches '${wanted}'. Available:\n${listing(gpus)}`,
		);
	}
	if (matched.length > 1) {
		throw new AmbiguousGpuSelection(
			`virtual-gpu: '${wanted}' matches ${matched.length} GPUs:\n${listing(gpus, matched)}`,
		);
	}
	return matched[0];
}

/**
 * An xorg.conf that drives `gpu` with a virtual screen and no outputs.
 *
 * `UseDisplayDevice "None"` keeps the NVIDIA driver off every connector, so it
 * needs no DRM master and coexists with a desktop on the same card.
 */
export function xorgConfig(gpu: GpuDevice, screen = GPU_SCREEN): string {
	const [width, height, depth] = screen.split("x");
	const driver = xorgDriver(gpu);
	const offscreen =
		driver === "nvidia" ? '\tOption      "UseDisplayDevice" "None"\n' : "";
	return `# Generated by camoufox for headless="virtual-gpu".
# GPU: ${gpu.pciAddress} ${gpuVendor(gpu)} [${gpu.vendorId}:${gpu.deviceId}] driver=${gpu.kernelDriver}
Section "ServerFlags"
\tOption      "AutoAddDevices" "false"
\tOption      "AutoAddGPU"     "false"
\tOption      "DontVTSwitch"   "true"
\tOption      "AllowMouseOpenFail" "true"
EndSection

Section "Device"
\tIdentifier  "camoufox-gpu"
\tDriver      "${driver}"
\tBusID       "${busId(gpu)}"
${offscreen}\tOption      "AllowEmptyInitialConfiguration" "true"
EndSection

Section "Monitor"
\tIdentifier  "camoufox-monitor"
\tHorizSync   5.0 - 1000.0
\tVertRefresh 5.0 - 200.0
EndSection

Section "Screen"
\tIdentifier  "camoufox-screen"
\tDevice      "camoufox-gpu"
\tMonitor     "camoufox-monitor"
\tDefaultDepth ${depth}
\tSubSection "Display"
\t\tDepth   ${depth}
\t\tVirtual ${width} ${height}
\tEndSubSection
EndSection

Section "ServerLayout"
\tIdentifier  "camoufox-layout"
\tScreen      "camoufox-screen"
EndSection
`;
}

/** The config's file name in /etc/X11, keyed by PCI address. */
export function configName(gpu: GpuDevice): string {
	return `camoufox-gpu-${gpu.pciAddress.replace(/[:.]/g, "_")}.conf`;
}

/** The one command that sets this machine up for `gpu`. */
export function setupCommand(gpu: GpuDevice): string {
	const sudo = process.getuid?.() === 0 ? "" : "sudo ";
	return `npx camoufox gpu-setup ${gpu.pciAddress} | ${sudo}sh`;
}

/**
 * A root shell script that sets this machine up for headless="virtual-gpu" on
 * `gpu`: Xorg and its setuid wrapper, the wrapper's settings, and the card's
 * config. Safe to run again.
 */
export function setupScript(gpu: GpuDevice): string {
	const config = path.join(GpuDisplay.configDir, configName(gpu));
	const xwrapper = GpuDisplay.xwrapperConfig;
	const settings = Object.entries(XWRAPPER_SETTINGS)
		.map(([key, value]) => `${key}=${value}\\n`)
		.join("");
	const deletes = Object.keys(XWRAPPER_SETTINGS)
		.map((key) => `-e '/^[[:space:]]*${key}[[:space:]]*=/d'`)
		.join(" ");
	const nvidia =
		xorgDriver(gpu) === "nvidia"
			? "\n" +
				"if ! find /usr/lib /usr/lib64 -name nvidia_drv.so 2>/dev/null | grep -q .; then\n" +
				"\techo 'camoufox gpu-setup: no nvidia_drv.so found. Install the NVIDIA driver'\\''s Xorg " +
				"module, matching the kernel driver (on Ubuntu, xserver-xorg-video-nvidia-<version>).' >&2\n" +
				"fi\n"
			: "";
	return `#!/bin/sh
# Generated by camoufox gpu-setup for headless="virtual-gpu".
# GPU: ${describeGpu(gpu)}
# Run once as root: ${setupCommand(gpu)}
set -e
if [ "$(id -u)" -ne 0 ]; then
\techo 'camoufox gpu-setup: run this as root (pipe it to sudo sh).' >&2
\texit 1
fi

# 1. The Xorg server and its setuid wrapper, Xorg.wrap.
if command -v apt-get >/dev/null 2>&1; then
\tdpkg -s xserver-xorg-core xserver-xorg-legacy >/dev/null 2>&1 \\
\t\t|| DEBIAN_FRONTEND=noninteractive apt-get install -y xserver-xorg-core xserver-xorg-legacy
elif ! command -v Xorg >/dev/null 2>&1; then
\techo 'camoufox gpu-setup: install the Xorg server and its setuid wrapper (Xorg.wrap), then run this again.' >&2
\texit 1
fi
${nvidia}
# 2. Let Xorg.wrap start Xorg as root for any user. A launch from ssh, systemd
#    or a container is not a console login. Any local user can then start a
#    root X server.
touch ${xwrapper}
sed -i ${deletes} ${xwrapper}
printf '${settings}' >> ${xwrapper}

# 3. The card's config, bound by PCI address.
cat > ${config} <<'CAMOUFOX_XORG_CONF'
${xorgConfig(gpu)}CAMOUFOX_XORG_CONF

echo 'headless="virtual-gpu" is set up for ${gpu.pciAddress}.'
`;
}

/** What keeps Xorg.wrap from starting Xorg for this user, if anything. */
export function setupProblems(): string[] {
	const problems: string[] = [];
	const wrappers = GpuDisplay.xorgWrappers;
	if (!wrappers.some((wrapper) => fs.existsSync(wrapper))) {
		problems.push(`no setuid Xorg.wrap (${wrappers.join(" or ")})`);
	}
	const xwrapper = GpuDisplay.xwrapperConfig;
	const settings = new Map<string, string>();
	for (const line of read(xwrapper).split("\n")) {
		const at = line.indexOf("=");
		if (at >= 0)
			settings.set(line.slice(0, at).trim(), line.slice(at + 1).trim());
	}
	for (const [key, wanted] of Object.entries(XWRAPPER_SETTINGS)) {
		const have = settings.get(key) || "unset";
		if (have !== wanted)
			problems.push(`${xwrapper} has ${key}=${have}, needs ${key}=${wanted}`);
	}
	return problems;
}

/** The logind session on VT `vt`, which its user may activate without root. */
function sessionOnVt(vt: string): string | null {
	let sessions: string;
	try {
		sessions = execFileSync("loginctl", ["list-sessions", "--no-legend"], {
			encoding: "utf-8",
		});
	} catch {
		return null;
	}
	for (const line of sessions.split("\n")) {
		const session = line.trim().split(/\s+/)[0];
		if (!session) continue;
		try {
			const number = execFileSync(
				"loginctl",
				["show-session", session, "-p", "VTNr", "--value"],
				{ encoding: "utf-8" },
			).trim();
			if (number === vt) return session;
		} catch {}
	}
	return null;
}

function run(command: string, args: string[]): void {
	try {
		execFileSync(command, args, { stdio: "ignore" });
	} catch {}
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * A headless Xorg server on one GPU, for headless="virtual-gpu".
 *
 * As root, Xorg takes a temporary config and log. Otherwise it runs through
 * the setuid Xorg.wrap, which accepts only a config name relative to /etc/X11
 * and no -logfile, so the config is installed there once.
 */
export class GpuDisplay extends VirtualDisplay {
	/** Where the config is installed for the setuid wrapper. */
	static configDir = SYSTEM_CONFIG_DIR;
	/** Xorg.wrap's settings. */
	static xwrapperConfig = XWRAPPER_CONFIG;
	/** Where the setuid wrapper may be installed. */
	static xorgWrappers: readonly string[] = XORG_WRAPPERS;
	gpu: GpuDevice;
	requireGpu: boolean;
	private client: net.Socket | null = null;
	private tempFiles: string[] = [];
	private vt: string | null = null;
	private vtTaken = false;

	constructor(gpu: GpuDevice, debug = false, requireGpu = true) {
		super(debug, GPU_SCREEN);
		this.serverName = "Xorg";
		this.gpu = gpu;
		this.requireGpu = requireGpu;
	}

	get xorgPath(): string {
		try {
			return execFileSync("which", ["Xorg"], {
				encoding: "utf-8",
				stdio: ["ignore", "pipe", "ignore"],
			}).trim();
		} catch {
			throw new CannotFindXorg(
				'headless="virtual-gpu" needs the Xorg server. Set this machine up with:\n' +
					`  ${setupCommand(this.gpu)}`,
			);
		}
	}

	/** A failed start, with what the machine is missing when that is why. */
	protected error(message: string): Error {
		if (process.getuid?.() !== 0) {
			const problems = setupProblems();
			if (problems.length) {
				message +=
					'\nheadless="virtual-gpu" without root needs Xorg.wrap to start Xorg as root:\n' +
					problems.map((problem) => `  - ${problem}\n`).join("") +
					`Set this machine up with:\n  ${setupCommand(this.gpu)}`;
			}
		}
		return new CannotExecuteXorg(message);
	}

	// No parent-death signal: the setuid Xorg.wrap drops it on exec. The held
	// client and -terminate end the server instead (ready()).
	protected wrapper(): string[] {
		return [];
	}

	protected command(): string[] {
		let files: string[];
		if (process.getuid?.() === 0) {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-xorg-"));
			const config = path.join(dir, "xorg.conf");
			fs.writeFileSync(config, xorgConfig(this.gpu, this.screen), {
				mode: 0o600,
			});
			const log = path.join(dir, "xorg.log");
			this.tempFiles = [dir, log];
			files = ["-config", config, "-logfile", log];
		} else {
			const name = configName(this.gpu);
			const installed = path.join(GpuDisplay.configDir, name);
			if (!fs.existsSync(installed)) {
				throw new CannotExecuteXorg(
					`headless="virtual-gpu" without root needs ${installed}. ` +
						`Set this machine up with:\n  ${setupCommand(this.gpu)}`,
				);
			}
			files = ["-config", name];
		}
		return [this.xorgPath, ...files, ...SERVER_FLAGS];
	}

	protected serverEnv(): NodeJS.ProcessEnv {
		return process.env;
	}

	private get log(): string {
		return this.tempFiles[1] ?? `/var/log/Xorg.${this._display}.log`;
	}

	async get(): Promise<string> {
		this.vt = read(ACTIVE_VT) || null;
		this.vtTaken = false;
		const vt = this.vt;
		const guard = vt
			? setInterval(() => {
					if (read(ACTIVE_VT) !== vt) this.vtTaken = true;
				}, 100)
			: null;
		try {
			const display = await super.get();
			if (this.vtTaken) this.failVt();
			return display;
		} finally {
			if (guard) clearInterval(guard);
		}
	}

	protected async ready(): Promise<void> {
		const deadline = Date.now() + SETTLE_MS;
		while (Date.now() < deadline) {
			if (this.vtTaken) this.failVt();
			const proc = this.proc;
			if (proc && (proc.exitCode !== null || proc.signalCode !== null)) {
				const error = this.error(
					`Xorg exited (${proc.exitCode ?? proc.signalCode}) right after starting. See ${this.log}.`,
				);
				this.kill();
				throw error;
			}
			await sleep(100);
		}
		// The server exits at its last client's disconnect (-terminate), and a
		// server no client ever reached never does. Holding one client from here
		// on means it always has a last client: this one, closed by kill() or by
		// the kernel when this process dies. An unprivileged launcher may not be
		// able to signal a root Xorg, so this is the teardown that always works.
		const client = net.connect({ path: `/tmp/.X11-unix/X${this._display}` });
		try {
			await new Promise<void>((resolve, reject) => {
				client.once("connect", resolve);
				client.once("error", reject);
			});
		} catch (error) {
			this.kill();
			throw this.error(
				`Could not connect to the Xorg display it reported: ${error}`,
			);
		}
		client.on("error", () => {});
		client.write(X11_SETUP);
		// Never keeps the launcher's event loop alive.
		client.unref();
		this.client = client;
	}

	private failVt(): never {
		const vt = this.vt ?? "";
		const number = vt.replace(/^tty/, "");
		const session = sessionOnVt(number);
		if (session) run("loginctl", ["activate", session]);
		if (read(ACTIVE_VT) !== vt) run("chvt", [number]);
		const restored = read(ACTIVE_VT) === vt;
		this.kill();
		throw new GpuVtTakeover(
			`Xorg on ${describeGpu(this.gpu)} switched the active VT away from ${vt}. ` +
				(restored
					? "It was switched back."
					: `Switch back with \`sudo chvt ${number}\`.`),
		);
	}

	/** Every process started with DISPLAY set to this display, except Xorg and us. */
	private displayProcesses(): number[] {
		const needle = `\0DISPLAY=:${this._display}\0`;
		const skip = new Set([process.pid, this.proc?.pid]);
		const pids: number[] = [];
		for (const entry of list("/proc")) {
			if (!/^\d+$/.test(entry) || skip.has(Number(entry))) continue;
			try {
				const environ = fs.readFileSync(`/proc/${entry}/environ`, "latin1");
				if (`\0${environ}`.includes(needle)) pids.push(Number(entry));
			} catch {}
		}
		return pids;
	}

	/**
	 * Whether a process on this display renders on the GPU.
	 *
	 * Firefox opens the card's DRM nodes for DMABuf even when it renders in
	 * software, so an open render node proves nothing. Rendering is the NVIDIA
	 * driver's /dev/nvidia<minor> held open, or work the kernel accounted to a
	 * GPU engine on one of the card's DRM nodes.
	 */
	usesGpu(): boolean {
		const nodes = drmNodes(this.gpu);
		for (const pid of this.displayProcesses()) {
			for (const fd of list(`/proc/${pid}/fd`)) {
				try {
					const target = fs.readlinkSync(`/proc/${pid}/fd/${fd}`);
					if (
						target === this.gpu.nvidiaNode ||
						(nodes.includes(target) &&
							drewOnGpu(fs.readFileSync(`/proc/${pid}/fdinfo/${fd}`, "utf-8")))
					)
						return true;
				} catch {}
			}
		}
		return false;
	}

	async waitForGpu(): Promise<boolean> {
		const waitS = Number(process.env[GPU_WAIT_ENV_VAR]) || GPU_WAIT_S;
		const deadline = Date.now() + waitS * 1000;
		while (Date.now() < deadline) {
			if (this.usesGpu()) return true;
			await sleep(250);
		}
		return false;
	}

	/** Throw, or warn with require_gpu: false, when the browser did not use the GPU. */
	checkGpu(active: boolean): void {
		if (active) return;
		if (!this.requireGpu) {
			LeakWarning.warn("gpu_software_rendering");
			return;
		}
		throw new GpuSoftwareFallback(
			`The browser on :${this._display} never rendered on ${describeGpu(this.gpu)}, so it renders ` +
				"in software. Firefox may have blocklisted the driver or failed to create a GPU " +
				`context. See ${this.log}.`,
		);
	}

	kill(): void {
		this.client?.destroy();
		this.client = null;
		if (this._display !== null) {
			// The browser's helpers (dbus, at-spi) are not in its process group.
			for (const signal of ["SIGTERM", "SIGKILL"] as const) {
				for (const pid of this.displayProcesses()) {
					try {
						process.kill(pid, signal);
					} catch {}
				}
				const deadline = Date.now() + 1500;
				while (this.displayProcesses().length && Date.now() < deadline) {
					Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
				}
			}
		}
		// SIGTERM lets Xorg remove its root-owned socket, which this process
		// cannot; the base kill() SIGKILLs only a server still running after that.
		const proc = this.proc;
		if (proc && proc.exitCode === null && proc.signalCode === null) {
			try {
				proc.kill("SIGTERM");
			} catch {}
			const deadline = Date.now() + 10_000;
			while (!exited(proc.pid) && Date.now() < deadline) {
				Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
			}
		}
		super.kill();
		if (this.tempFiles.length) {
			fs.rmSync(this.tempFiles[0], { recursive: true, force: true });
			this.tempFiles = [];
		}
		this._display = null;
	}
}

/** Whether `pid` has exited (a zombie counts: it renders nothing). */
function exited(pid: number | undefined): boolean {
	if (!pid) return true;
	const stat = read(`/proc/${pid}/stat`);
	return !stat || / Z /.test(stat.slice(stat.lastIndexOf(")")));
}

/** Something that opens pages: a Browser or a BrowserContext. */
interface PageOpener {
	newPage(): Promise<{
		goto(url: string): Promise<unknown>;
		close(): Promise<void>;
	}>;
}

/** Draw in a page of `target` and check the browser rendered on the GPU. */
export async function proveGpu(
	target: PageOpener,
	display: GpuDisplay,
): Promise<void> {
	const page = await target.newPage();
	let active: boolean;
	try {
		await page.goto(PROBE_PAGE);
		active = await display.waitForGpu();
	} finally {
		await page.close();
	}
	display.checkGpu(active);
}
