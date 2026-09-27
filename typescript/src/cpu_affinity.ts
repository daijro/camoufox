/**
 * Pin the browser to as many CPU cores as the identity reports.
 *
 * TypeScript twin of pythonlib/camoufox/cpu_affinity.py.
 *
 * navigator.hardwareConcurrency is spoofed by the browser, but the number of
 * cores a page can *measure* (timing N parallel workers) is the number the OS
 * lets the browser run on. Reporting the fingerprint's value and pinning the
 * browser's CPU affinity to that many cores makes the two agree, so the drawn
 * value survives instead of being replaced by the host count.
 *
 * Python pins the Playwright driver (a separate Node process) right before the
 * launch; here the driver IS this process -- playwright-core spawns the browser
 * from the main thread -- so the pin is applied to this process's main thread
 * and lifted again afterwards. Child processes inherit the affinity mask on
 * Linux and Windows, so the browser and every content/GPU process it spawns
 * run on the pinned set. macOS has no process affinity API, so nothing can be
 * pinned there and the launcher falls back to reporting the host's (snapped)
 * count.
 *
 * Node has no sched_setaffinity binding, so Linux goes through util-linux's
 * `taskset` (which, like os.sched_setaffinity(pid), sets the thread whose TID
 * is `pid` -- the main thread) and Windows through PowerShell's
 * Process.ProcessorAffinity.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";

function run(command: string, args: string[]): string | null {
	try {
		return execFileSync(command, args, {
			encoding: "utf-8",
			stdio: ["ignore", "pipe", "ignore"],
			timeout: 10_000,
			windowsHide: true,
		});
	} catch {
		return null;
	}
}

let tasksetAvailable: boolean | undefined;

/** Whether this host can constrain a process to a subset of its cores. */
export function supported(): boolean {
	if (process.platform === "linux") {
		// Python checks hasattr(os, 'sched_setaffinity'), which is always true on
		// Linux. The equivalent capability here is the taskset binary.
		tasksetAvailable ??= run("taskset", ["-V"]) !== null;
		return tasksetAvailable;
	}
	return process.platform === "win32";
}

/** Parse a Linux cpu list ("0-3,8,10-11") into sorted core numbers. */
export function parseCpuList(list: string): number[] {
	const cores = new Set<number>();
	for (const part of list.trim().split(",")) {
		if (!part) continue;
		const [lo, hi] = part.split("-").map((n) => Number.parseInt(n, 10));
		if (Number.isNaN(lo)) continue;
		const top = hi === undefined || Number.isNaN(hi) ? lo : hi;
		for (let c = lo; c <= top; c++) {
			cores.add(c);
		}
	}
	return [...cores].sort((a, b) => a - b);
}

function linuxGetAffinity(pid: number): number[] | null {
	try {
		const status = fs.readFileSync(`/proc/${pid}/status`, "utf-8");
		const match = status.match(/^Cpus_allowed_list:\s*(.+)$/m);
		if (match) {
			const cores = parseCpuList(match[1]);
			if (cores.length) return cores;
		}
	} catch {
		// fall through
	}
	return null;
}

function linuxSetAffinity(pid: number, cores: Iterable<number>): boolean {
	const list = [...cores].sort((a, b) => a - b).join(",");
	return run("taskset", ["-p", "-c", list, String(pid)]) !== null;
}

/** The cores this process may run on, in order. */
export function hostCores(): number[] | null {
	if (process.platform === "linux") {
		const cores = linuxGetAffinity(process.pid);
		if (cores) return cores;
	}
	if (process.platform === "win32") {
		const mask = winGetMask(process.pid);
		if (mask) return maskToCores(mask);
	}
	const n = os.cpus().length;
	return n ? Array.from({ length: n }, (_, i) => i) : null;
}

let hostCountSnapshot: number | undefined;

/**
 * How many cores the host lets this process use, as read before this process
 * first pinned itself. playwright-core spawns the browser from this process,
 * so pin() narrows this process's own mask during a launch; a live reading
 * taken then by a concurrent launch (hostCores(), or Node's
 * availableParallelism()) would see the pinned count and pass it off as the
 * host's. Python pins a separate driver process and never has this problem.
 */
export function hostCoreCount(): number {
	hostCountSnapshot ??=
		hostCores()?.length || os.availableParallelism() || os.cpus().length;
	return hostCountSnapshot;
}

/**
 * `count` adjacent cores from a random starting point (wrapping). Always
 * taking the first `count` stacked every browser on one host onto cores
 * 0..count-1, so concurrent browsers measured far less parallelism than they
 * report; adjacent cores keep the SMT topology a real machine of that size
 * would have.
 */
export function pick(cores: readonly number[], count: number): number[] {
	const start = Math.floor(Math.random() * cores.length);
	return [...cores.slice(start), ...cores.slice(0, start)]
		.slice(0, count)
		.sort((a, b) => a - b);
}

/**
 * Restrict `pid` to `count` of its cores. Returns the previous set so it can
 * be handed back to `restore()`, or null if nothing was changed.
 *
 * The caller must not pin the same process for two launches at once: the
 * browser inherits whatever mask the driver has when it is spawned.
 */
export function pin(pid: number, count: number): number[] | null {
	if (count < 1 || !supported()) return null;
	if (pid === process.pid) hostCoreCount(); // read the host before narrowing it
	if (process.platform === "linux") {
		const before = linuxGetAffinity(pid);
		if (!before || count >= before.length) return null;
		return linuxSetAffinity(pid, pick(before, count)) ? before : null;
	}
	if (process.platform === "win32") {
		const beforeMask = winGetMask(pid);
		if (!beforeMask) return null;
		const before = maskToCores(beforeMask);
		if (count >= before.length) return null;
		return winSetMask(pid, coresToMask(pick(before, count))) ? before : null;
	}
	return null;
}

/** Give `pid` back the cores it had before `pin()`. */
export function restore(pid: number, previous: readonly number[] | null): void {
	if (!previous?.length) return;
	if (process.platform === "linux") {
		linuxSetAffinity(pid, previous);
	} else if (process.platform === "win32") {
		winSetMask(pid, coresToMask(previous));
	}
}

// -- Windows ---------------------------------------------------------------

export function maskToCores(mask: bigint): number[] {
	const cores: number[] = [];
	for (let i = 0; mask >> BigInt(i) > 0n; i++) {
		if ((mask >> BigInt(i)) & 1n) cores.push(i);
	}
	return cores;
}

export function coresToMask(cores: Iterable<number>): bigint {
	let mask = 0n;
	for (const c of cores) mask |= 1n << BigInt(c);
	return mask;
}

function winGetMask(pid: number): bigint {
	const out = run("powershell", [
		"-NoProfile",
		"-Command",
		`[int64](Get-Process -Id ${pid}).ProcessorAffinity`,
	]);
	if (!out) return 0n;
	try {
		return BigInt(out.trim());
	} catch {
		return 0n;
	}
}

function winSetMask(pid: number, mask: bigint): boolean {
	return (
		run("powershell", [
			"-NoProfile",
			"-Command",
			`(Get-Process -Id ${pid}).ProcessorAffinity = [IntPtr][int64]${mask}`,
		]) !== null
	);
}

// -- launch serialisation --------------------------------------------------

let pinChain: Promise<unknown> = Promise.resolve();
let everPinned = false;

/**
 * Run `fn` while holding the process-wide pin lock. The browser inherits the
 * driver's mask at spawn, so two concurrent launches must not interleave
 * pin/restore: the second pin would land on the first browser, and the first
 * restore would leave the driver pinned. (Python: async_api._pin_lock.)
 */
export function withPinLock<T>(fn: () => Promise<T>): Promise<T> {
	everPinned = true;
	const result = pinChain.then(fn, fn);
	pinChain = result.catch(() => undefined);
	return result;
}

/**
 * Run an UNPINNED launch. It spawns a browser too, which inherits whatever
 * mask this process has at that moment, so once any launch in this process
 * has pinned, it waits for the lock rather than spawning into another
 * launch's pin. Until then (pin_cpu_cores is opt-in) it runs straight away.
 */
export function withUnpinnedLaunch<T>(fn: () => Promise<T>): Promise<T> {
	return everPinned ? withPinLock(fn) : fn();
}
