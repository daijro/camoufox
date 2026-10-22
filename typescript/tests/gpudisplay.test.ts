/**
 * Tests for gpudisplay.ts (headless="virtual-gpu") that need no GPU:
 * enumeration and selection on a fake sysfs tree, the generated xorg.conf, the
 * Xorg argv, the browser's environment and prefs, the identity's GPU probe,
 * the GPU-use check, and teardown.
 *
 * Twin of python/tests/test_gpudisplay.py. The real display is
 * gpu-display.test.ts.
 */
import { type ChildProcess, execFileSync, spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import {
	HOME,
	quietly,
	restoreDeps,
	stubHost,
	utils,
	warnings,
} from "./launch-host.js";

const {
	AmbiguousGpuSelection,
	CannotExecuteXorg,
	GpuNotFound,
	GpuSoftwareFallback,
	NoGpuFound,
	VirtualDisplayError,
} = await import("../src/exceptions.js");
const gpudisplay = await import("../src/gpudisplay.js");
const {
	busId,
	configName,
	drewOnGpu,
	enumerateGpus,
	GPU_PREFS,
	GpuDisplay,
	PROBE_PAGE,
	SERVER_FLAGS,
	selectGpu,
	xorgConfig,
	xorgDriver,
} = gpudisplay;
type GpuDevice = import("../src/gpudisplay.js").GpuDevice;
const { hostGpu } = await import("../src/host_rendering.js");
const { firefox } = await import("playwright-core");

const deps = utils.utilsDeps;

const NVIDIA: GpuDevice = {
	pciAddress: "0000:01:00.0",
	renderNode: "/dev/dri/renderD129",
	cardNode: "/dev/dri/card1",
	vendorId: "0x10de",
	deviceId: "0x2c02",
	kernelDriver: "nvidia",
	nvidiaNode: "/dev/nvidia0",
};
const AMD: GpuDevice = {
	pciAddress: "0000:6f:00.0",
	renderNode: "/dev/dri/renderD128",
	cardNode: "/dev/dri/card0",
	vendorId: "0x1002",
	deviceId: "0x744c",
	kernelDriver: "amdgpu",
	nvidiaNode: null,
};
const AMD_IGPU: GpuDevice = {
	pciAddress: "0000:70:00.0",
	renderNode: "/dev/dri/renderD130",
	cardNode: "/dev/dri/card3",
	vendorId: "0x1002",
	deviceId: "0x13c0",
	kernelDriver: "amdgpu",
	nvidiaNode: null,
};
const HOST = [NVIDIA, AMD, AMD_IGPU];

const scratch: string[] = [];
function tmpdir(): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-gpu-test-"));
	scratch.push(dir);
	return dir;
}

afterEach(() => {
	restoreDeps();
	vi.restoreAllMocks();
	vi.unstubAllEnvs();
	for (const dir of scratch.splice(0))
		fs.rmSync(dir, { recursive: true, force: true });
});

/** This machine's layout: the render nodes are numbered in driver load order,
 * so the AMD card is renderD128 though the NVIDIA one has the lower address. */
function fakeHost(): string {
	const root = tmpdir();
	fs.mkdirSync(path.join(root, "dev/dri"), { recursive: true });
	fs.mkdirSync(path.join(root, "sys/class/drm"), { recursive: true });
	const device = (pci: string, vendor: string, id: string, driver: string) => {
		const dir = path.join(root, "sys/devices/pci0000:00", pci);
		fs.mkdirSync(dir, { recursive: true });
		fs.writeFileSync(path.join(dir, "vendor"), `${vendor}\n`);
		fs.writeFileSync(path.join(dir, "device"), `${id}\n`);
		fs.writeFileSync(
			path.join(dir, "uevent"),
			`DRIVER=${driver}\nPCI_SLOT_NAME=${pci}\n`,
		);
		return dir;
	};
	const node = (name: string, dir: string) => {
		fs.writeFileSync(path.join(root, "dev/dri", name), "");
		fs.mkdirSync(path.join(root, "sys/class/drm", name));
		fs.symlinkSync(dir, path.join(root, "sys/class/drm", name, "device"));
	};
	const nvidia = device("0000:01:00.0", "0x10de", "0x2c02", "nvidia");
	const amd = device("0000:6f:00.0", "0x1002", "0x744C", "amdgpu");
	const igpu = device("0000:70:00.0", "0x1002", "0x13c0", "amdgpu");
	node("renderD128", amd);
	node("card0", amd);
	node("renderD129", nvidia);
	node("card1", nvidia);
	node("renderD130", igpu);
	node("card3", igpu);
	// A connector is a card*-named entry that is not a card.
	fs.mkdirSync(path.join(root, "sys/class/drm/card1-DP-1"));
	// A render node with no PCI device cannot be bound by BusID.
	const platform = path.join(root, "sys/devices/platform/vgem");
	fs.mkdirSync(platform, { recursive: true });
	node("renderD131", platform);
	const info = path.join(root, "proc/driver/nvidia/gpus/0000:01:00.0");
	fs.mkdirSync(info, { recursive: true });
	fs.writeFileSync(
		path.join(info, "information"),
		"Model: \t NVIDIA GeForce RTX 5080\nDevice Minor: \t 0\n",
	);
	return root;
}

describe.runIf(process.platform === "linux")("enumeration", () => {
	it("lists PCI GPUs in address order, not render node order", () => {
		expect(enumerateGpus(fakeHost())).toEqual(HOST);
	});

	it("finds no GPUs without /dev/dri", () => {
		expect(enumerateGpus(tmpdir())).toEqual([]);
	});

	it("writes the bus ID in decimal without the domain", () => {
		expect(busId(NVIDIA)).toBe("PCI:1:0:0");
		expect(busId(AMD)).toBe("PCI:111:0:0");
	});

	it("gives NVIDIA its own driver and everything else modesetting", () => {
		expect(xorgDriver(NVIDIA)).toBe("nvidia");
		expect(xorgDriver(AMD)).toBe("modesetting");
	});
});

describe("selection", () => {
	it.each([
		0,
		"0",
		"renderD129",
		"/dev/dri/renderD129",
		"card1",
		"/dev/dri/card1",
		"01:00.0",
		"0000:01:00.0",
		"10de:2c02",
		"0x10de:0x2c02",
		"nvidia",
		"NVIDIA",
	])("%s names the NVIDIA card", (selector) => {
		expect(selectGpu(selector, HOST)).toEqual(NVIDIA);
	});

	it("a PCI address names the AMD card", () => {
		expect(selectGpu("6f:00.0", HOST)).toEqual(AMD);
	});

	it("the environment names the card when the option does not", () => {
		vi.stubEnv("CAMOUFOX_GPU", "6f:00.0");
		expect(selectGpu(undefined, HOST)).toEqual(AMD);
		expect(selectGpu("01:00.0", HOST)).toEqual(NVIDIA);
	});

	it("a lone GPU needs no selector", () => {
		vi.stubEnv("CAMOUFOX_GPU", "");
		expect(selectGpu(undefined, [AMD])).toEqual(AMD);
	});

	it("several GPUs and no selector is ambiguous", () => {
		vi.stubEnv("CAMOUFOX_GPU", "");
		expect(() => selectGpu(undefined, HOST)).toThrow(AmbiguousGpuSelection);
	});

	it("a selector matching two GPUs is ambiguous", () => {
		expect(() => selectGpu("amd", HOST)).toThrow(/\[1\][\s\S]*\[2\]/);
	});

	it("a selector matching nothing fails", () => {
		expect(() => selectGpu("intel", HOST)).toThrow(GpuNotFound);
		expect(() => selectGpu(3, HOST)).toThrow(GpuNotFound);
		expect(() => selectGpu("intel", HOST)).toThrow(VirtualDisplayError);
	});

	it("no GPUs fails", () => {
		expect(() => selectGpu("0", [])).toThrow(NoGpuFound);
	});
});

describe("xorg.conf", () => {
	it("drives NVIDIA offscreen", () => {
		const config = xorgConfig(NVIDIA);
		for (const line of [
			'Option      "AutoAddDevices" "false"',
			'Option      "AutoAddGPU"     "false"',
			'Option      "DontVTSwitch"   "true"',
			'Option      "AllowMouseOpenFail" "true"',
			'Driver      "nvidia"',
			'BusID       "PCI:1:0:0"',
			'Option      "UseDisplayDevice" "None"',
			'Option      "AllowEmptyInitialConfiguration" "true"',
			"HorizSync   5.0 - 1000.0",
			"VertRefresh 5.0 - 200.0",
			"DefaultDepth 24",
			"Virtual 1920 1080",
		])
			expect(config).toContain(line);
	});

	it("drives other cards with modesetting, without the NVIDIA option", () => {
		const config = xorgConfig(AMD);
		expect(config).toContain('Driver      "modesetting"');
		expect(config).toContain('BusID       "PCI:111:0:0"');
		expect(config).not.toContain("UseDisplayDevice");
	});

	it("names no render node, which can change between boots", () => {
		expect(xorgConfig(NVIDIA)).not.toContain("renderD");
	});

	it("is named by PCI address", () => {
		expect(configName(NVIDIA)).toBe("camoufox-gpu-0000_01_00_0.conf");
	});
});

describe("the Xorg command", () => {
	function display(gpu: GpuDevice) {
		const d = new GpuDisplay(gpu);
		Object.defineProperty(d, "xorgPath", { get: () => "/usr/bin/Xorg" });
		return d as any;
	}

	function configDir(): string {
		const dir = tmpdir();
		const installed = GpuDisplay.configDir;
		GpuDisplay.configDir = dir;
		onTestFinished(() => {
			GpuDisplay.configDir = installed;
		});
		return dir;
	}

	it("names the installed config without root", () => {
		vi.spyOn(process, "getuid").mockReturnValue(1000);
		fs.writeFileSync(
			path.join(configDir(), configName(NVIDIA)),
			xorgConfig(NVIDIA),
		);
		expect(display(NVIDIA).command()).toEqual([
			"/usr/bin/Xorg",
			"-config",
			"camoufox-gpu-0000_01_00_0.conf",
			"-terminate",
			"2",
			"-nolisten",
			"tcp",
			"-sharevts",
			"-novtswitch",
		]);
	});

	it("says how to install a missing config without root", () => {
		vi.spyOn(process, "getuid").mockReturnValue(1000);
		const dir = configDir();
		expect(() => display(NVIDIA).command()).toThrow(CannotExecuteXorg);
		expect(() => display(NVIDIA).command()).toThrow(
			`needs ${dir}/camoufox-gpu-0000_01_00_0.conf. Set this machine up with:\n` +
				"  npx camoufox gpu-setup 0000:01:00.0 | sudo sh",
		);
	});

	it("names the setup command when Xorg is missing", () => {
		vi.spyOn(process, "getuid").mockReturnValue(0);
		const d = new GpuDisplay(AMD) as any;
		expect(() => {
			const original = process.env.PATH;
			process.env.PATH = "";
			try {
				return d.xorgPath;
			} finally {
				process.env.PATH = original;
			}
		}).toThrow(
			// As root the script needs no sudo.
			/needs the Xorg server\. Set this machine up with:\n {2}npx camoufox gpu-setup 0000:6f:00\.0 \| sh$/,
		);
	});

	it("uses a temporary config and log as root, and removes them", () => {
		vi.spyOn(process, "getuid").mockReturnValue(0);
		const d = display(AMD);
		const command: string[] = d.command();
		const config = command[command.indexOf("-config") + 1];
		const log = command[command.indexOf("-logfile") + 1];
		expect(path.isAbsolute(config)).toBe(true);
		expect(fs.readFileSync(config, "utf-8")).toBe(xorgConfig(AMD));
		expect(command.slice(-6)).toEqual([...SERVER_FLAGS]);
		fs.writeFileSync(log, "");
		d.kill();
		expect(fs.existsSync(config) || fs.existsSync(log)).toBe(false);
	});

	it("leaves the server's environment untouched", () => {
		// Xvfb's server is forced onto Mesa's software GLX; this one must not be.
		expect((new GpuDisplay(NVIDIA) as any).serverEnv()).toBe(process.env);
	});
});

describe("the launch", () => {
	function started() {
		deps.selectGpu = () => NVIDIA;
		vi.spyOn(GpuDisplay.prototype, "get").mockResolvedValue(":77");
	}

	it("points the launch at the display, with the GPU prefs", async () => {
		started();
		const options: Record<string, any> = {
			gpu: "01:00.0",
			firefox_user_prefs: { "gfx.webrender.all": false },
		};
		const [display, headless] = await utils.startVirtualDisplay(
			"virtual-gpu",
			false,
			options,
		);
		expect(display).toBeInstanceOf(GpuDisplay);
		expect((display as any).requireGpu).toBe(true);
		expect(headless).toBe(false);
		expect(options).toEqual({
			virtual_display: ":77",
			// The caller's prefs win.
			firefox_user_prefs: { ...GPU_PREFS, "gfx.webrender.all": false },
		});
	});

	it("only warns with require_gpu: false", async () => {
		started();
		const [display] = await utils.startVirtualDisplay("virtual-gpu", false, {
			require_gpu: false,
		} as any);
		expect((display as any).requireGpu).toBe(false);
	});

	it.each([
		"gpu",
		"require_gpu",
	])("refuses %s without virtual-gpu", async (option) => {
		await expect(
			utils.startVirtualDisplay("virtual", false, { [option]: "0" } as any),
		).rejects.toThrow(/virtual-gpu/);
	});

	it("gives the browser X11 settings but no GPU overrides", async () => {
		started();
		stubHost();
		const options: Record<string, any> = { gpu: "0" };
		await utils.startVirtualDisplay("virtual-gpu", false, options);
		const launched = await quietly(() =>
			utils.launchOptions({
				...options,
				env: { HOME },
				headless: false,
				i_know_what_im_doing: true,
			}),
		);
		expect(launched.env.DISPLAY).toBe(":77");
		const overrides = Object.keys(launched.env).filter((key) =>
			/^(MESA_|__GLX_|LIBGL_|DRI_PRIME|__NV_)/.test(key),
		);
		expect(overrides).toEqual([]);
	});

	it("probes the identity's GPU on the GPU display, with its prefs", async () => {
		// The identity claims the GPU Firefox reports on the GPU display, not
		// the one the desktop renders on.
		started();
		stubHost();
		deps.hostOsKey = () => "lin";
		const probes: any[] = [];
		deps.hostGpu = async (_exe, _headless, env, prefs) => {
			probes.push([
				env.DISPLAY,
				Object.fromEntries(Object.keys(GPU_PREFS).map((k) => [k, prefs[k]])),
			]);
			return ["NVIDIA Corporation", "NVIDIA GeForce GTX 980, or similar"];
		};
		const options: Record<string, any> = { gpu: "0" };
		await utils.startVirtualDisplay("virtual-gpu", false, options);
		await quietly(() =>
			utils.launchOptions({
				...options,
				os: "linux",
				env: { HOME },
				headless: false,
				i_know_what_im_doing: true,
			}),
		);
		expect(probes).toEqual([[":77", GPU_PREFS]]);
	});

	it("reads the probe with the launch's rendering prefs only", () => {
		const launch = vi
			.spyOn(firefox, "launch")
			.mockImplementation(() => new Promise(() => undefined));
		hostGpu(
			"/x/camoufox",
			false,
			{ DISPLAY: ":77" },
			{ ...GPU_PREFS, "intl.locale.requested": "en-US" },
		);
		expect(launch.mock.calls[0][0]?.firefoxUserPrefs).toEqual({
			...GPU_PREFS,
			"webgl.force-enabled": true,
		});
	});
});

class FakePage {
	url: string | null = null;
	closed = false;
	async goto(url: string) {
		this.url = url;
	}
	async close() {
		this.closed = true;
	}
}

class FakeBrowser {
	page = new FakePage();
	closed = false;
	async newPage() {
		return this.page;
	}
	async close() {
		this.closed = true;
	}
}

describe("the GPU check", () => {
	it("keeps a browser that rendered on the GPU", async () => {
		const display = new GpuDisplay(NVIDIA);
		vi.spyOn(display, "waitForGpu").mockResolvedValue(true);
		const browser = new FakeBrowser();
		expect(await utils.attachVirtualDisplay(browser, display)).toBe(browser);
		expect(browser.page.url).toBe(PROBE_PAGE);
		expect(browser.page.closed).toBe(true);
		expect(browser.closed).toBe(false);
	});

	it("closes a browser in software and fails the launch", async () => {
		const display = new GpuDisplay(NVIDIA);
		vi.spyOn(display, "waitForGpu").mockResolvedValue(false);
		const kill = vi.spyOn(display, "kill").mockImplementation(() => {});
		const browser = new FakeBrowser();
		await expect(utils.attachVirtualDisplay(browser, display)).rejects.toThrow(
			GpuSoftwareFallback,
		);
		expect(browser.closed).toBe(true);
		expect(kill).toHaveBeenCalled();
	});

	it("warns instead with require_gpu: false", async () => {
		const display = new GpuDisplay(NVIDIA, false, false);
		vi.spyOn(display, "waitForGpu").mockResolvedValue(false);
		const { warnings: caught } = await warnings.recordWarnings(() =>
			utils.attachVirtualDisplay(new FakeBrowser(), display),
		);
		expect(
			caught.some(
				(w) => w.category === "LeakWarning" && w.message.includes("software"),
			),
		).toBe(true);
	});
});

// /proc/<pid>/fdinfo of Firefox's render node on an RX 7900 XTX, trimmed.
describe("setting a machine up", () => {
	function xwrapper(contents: string, wrapperExists = true): string {
		vi.spyOn(process, "getuid").mockReturnValue(1000);
		const dir = tmpdir();
		const config = path.join(dir, "Xwrapper.config");
		fs.writeFileSync(config, contents);
		const wrapper = path.join(dir, "Xorg.wrap");
		if (wrapperExists) fs.writeFileSync(wrapper, "");
		const saved = [GpuDisplay.xwrapperConfig, GpuDisplay.xorgWrappers] as const;
		GpuDisplay.xwrapperConfig = config;
		GpuDisplay.xorgWrappers = [wrapper];
		onTestFinished(() => {
			[GpuDisplay.xwrapperConfig, GpuDisplay.xorgWrappers] = saved;
		});
		return config;
	}
	const fail = (message: string) =>
		(new GpuDisplay(AMD) as any).error(message) as Error;

	it("names a stock wrapper's settings and the fix", () => {
		// What Debian and Ubuntu ship.
		const config = xwrapper("# Xwrapper.config\nallowed_users=console\n");
		const error = fail("Xorg exited (1) right after starting.");
		expect(error).toBeInstanceOf(CannotExecuteXorg);
		expect(error.message).toContain(
			`${config} has allowed_users=console, needs allowed_users=anybody`,
		);
		expect(error.message).toContain(
			`${config} has needs_root_rights=unset, needs needs_root_rights=yes`,
		);
		expect(error.message).toMatch(
			/npx camoufox gpu-setup 0000:6f:00\.0 \| sudo sh$/,
		);
	});

	it("names a missing wrapper", () => {
		xwrapper("allowed_users=anybody\nneeds_root_rights=yes\n", false);
		expect(gpudisplay.setupProblems()).toEqual([
			`no setuid Xorg.wrap (${GpuDisplay.xorgWrappers[0]})`,
		]);
	});

	it("adds nothing on a machine that is set up, or as root", () => {
		xwrapper("allowed_users = anybody\nneeds_root_rights = yes\n");
		expect(fail("Xorg exited (1).").message).toBe("Xorg exited (1).");
		xwrapper("allowed_users=console\n");
		vi.spyOn(process, "getuid").mockReturnValue(0);
		expect(fail("Xorg exited (1).").message).toBe("Xorg exited (1).");
	});

	it.each([
		["nvidia", NVIDIA],
		["amd", AMD],
	] as const)("prints a valid sh script for %s", (_, gpu) => {
		const script = gpudisplay.setupScript(gpu);
		expect(() =>
			execFileSync("sh", ["-n"], { input: script, stdio: "pipe" }),
		).not.toThrow();
		const config = path.join(GpuDisplay.configDir, configName(gpu));
		expect(script).toContain(
			`cat > ${config} <<'CAMOUFOX_XORG_CONF'\n${xorgConfig(gpu)}CAMOUFOX_XORG_CONF\n`,
		);
		expect(script).toContain(
			"printf 'allowed_users=anybody\\nneeds_root_rights=yes\\n'",
		);
		expect(script.includes("nvidia_drv.so")).toBe(gpu === NVIDIA);
	});
});

const AMDGPU_FDINFO = (gfx: number) =>
	`pos:\t0\nflags:\t02100002\ndrm-driver:\tamdgpu\ndrm-client-id:\t5873\n` +
	`drm-total-vram:\t159812 KiB\ndrm-engine-gfx:\t${gfx} ns\n` +
	`drm-engine-compute:\t0 ns\ndrm-engine-capacity-gfx:\t1\n`;

// From the kernel's Xe usage stats documentation.
const XE_FDINFO = (rcs: number) =>
	`pos:\t0\nflags:\t0100002\ndrm-driver:\txe\ndrm-client-id:\t21\n` +
	`drm-cycles-rcs:\t${rcs}\ndrm-total-cycles-rcs:\t7655183225\n` +
	`drm-cycles-bcs:\t0\ndrm-total-cycles-bcs:\t7655183225\n` +
	`drm-engine-capacity-vcs:\t2\n`;

/** A process on `display` that holds `file` open, as a browser holds the GPU. */
async function holding(file: string, display: string): Promise<ChildProcess> {
	const child = spawn(
		process.execPath,
		[
			"-e",
			`require("fs").openSync(${JSON.stringify(file)}, "r"); console.log(1); setTimeout(() => {}, 60000);`,
		],
		{
			env: { ...process.env, DISPLAY: display },
			stdio: ["ignore", "pipe", "ignore"],
		},
	);
	await new Promise((resolve) => child.stdout?.once("data", resolve));
	return child;
}

describe.runIf(process.platform === "linux")("GPU use", () => {
	// Rendering is read from what the kernel accounts to the browser, never
	// from the renderer string, which the identity spoofs.
	it("counts engine time on the render node as rendering", () => {
		expect(drewOnGpu(AMDGPU_FDINFO(39907610))).toBe(true);
	});

	it("counts xe's busy cycles, not its total cycles", () => {
		// xe reports cycles only; its total-cycles line grows on an idle client too.
		expect(drewOnGpu(XE_FDINFO(28257900))).toBe(true);
		expect(drewOnGpu(XE_FDINFO(0))).toBe(false);
	});

	it("reads engine work from both of the card's DRM nodes", () => {
		// On an RX 7900 XTX, a second launch from one process drew through
		// /dev/dri/card0 and left renderD128 idle.
		const amd = {
			...NVIDIA,
			renderNode: "/dev/dri/renderD128",
			cardNode: "/dev/dri/card0",
		};
		expect(gpudisplay.drmNodes(amd)).toEqual([
			"/dev/dri/renderD128",
			"/dev/dri/card0",
		]);
		expect(gpudisplay.drmNodes({ ...amd, cardNode: null })).toEqual([
			"/dev/dri/renderD128",
		]);
	});

	it("does not count an idle render node", () => {
		// Firefox opens it for DMABuf in software too; the capacity line is not time.
		expect(drewOnGpu(AMDGPU_FDINFO(0))).toBe(false);
		expect(drewOnGpu("pos:\t0\nflags:\t02\n")).toBe(false);
	});

	function card(): GpuDevice {
		const dir = tmpdir();
		for (const name of ["renderD200", "nvidia7"])
			fs.writeFileSync(path.join(dir, name), "");
		return {
			...NVIDIA,
			renderNode: path.join(dir, "renderD200"),
			nvidiaNode: path.join(dir, "nvidia7"),
		};
	}

	it.each([
		["nvidiaNode", ":98765", true],
		["nvidiaNode", ":987650", false],
		// An open render node with no engine time is software rendering.
		["renderNode", ":98765", false],
	] as const)("a process holding %s on %s renders: %s", async (held, on, rendering) => {
		const gpu = card();
		const display = new GpuDisplay(gpu) as any;
		display._display = 98765;
		const child = await holding(gpu[held] as string, on);
		try {
			expect(display.usesGpu()).toBe(rendering);
		} finally {
			child.kill("SIGKILL");
		}
	});

	it("kill sweeps every process on the display", async () => {
		const gpu = card();
		const display = new GpuDisplay(gpu) as any;
		display._display = 98765;
		const child = await holding(gpu.renderNode, ":98765");
		const exited = new Promise((resolve) => child.once("exit", resolve));
		try {
			display.kill();
			expect(await exited).not.toBeUndefined();
		} finally {
			child.kill("SIGKILL");
		}
	});
});

describe("the server", () => {
	// The served browser has no page of its own, so the check connects to the
	// endpoint and draws in a page there.
	async function serve(rendered: boolean) {
		stubHost();
		deps.selectGpu = () => NVIDIA;
		vi.spyOn(GpuDisplay.prototype, "get").mockResolvedValue(":77");
		vi.spyOn(GpuDisplay.prototype, "waitForGpu").mockResolvedValue(rendered);
		const kill = vi
			.spyOn(GpuDisplay.prototype, "kill")
			.mockImplementation(() => {});
		const server = {
			closed: false,
			wsEndpoint: () => "ws://localhost:4242/abc",
			on: () => server,
			async close() {
				server.closed = true;
			},
		};
		vi.spyOn(firefox, "launchServer").mockResolvedValue(server as any);
		const browser = new FakeBrowser();
		const connect = vi
			.spyOn(firefox, "connect")
			.mockResolvedValue(browser as any);
		const { launchServer } = await import("../src/server.js");
		const result = quietly(() =>
			launchServer({
				headless: "virtual-gpu",
				env: { HOME },
				i_know_what_im_doing: true,
			}),
		);
		return { result, server, browser, connect, kill };
	}

	it("checks the GPU on its endpoint", async () => {
		const { result, server, browser, connect } = await serve(true);
		expect(await result).toBe(server);
		expect(connect).toHaveBeenCalledWith("ws://localhost:4242/abc");
		expect(browser.page.url).toBe(PROBE_PAGE);
		expect(browser.closed).toBe(true);
		expect(server.closed).toBe(false);
	});

	it("closes a server whose browser renders in software", async () => {
		const { result, server, kill } = await serve(false);
		await expect(result).rejects.toThrow(GpuSoftwareFallback);
		expect(server.closed).toBe(true);
		expect(kill).toHaveBeenCalled();
	});
});
