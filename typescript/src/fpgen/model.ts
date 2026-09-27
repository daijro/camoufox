/**
 * Model files for the fpgen port: where they live, how they get there, and the
 * loaded model. Replaces fpgen/pkgman.py and the file half of fpgen/unpacker.py
 * (scrapfly/fingerprint-generator, Apache-2.0; see ./NOTICE).
 *
 * Deliberately NOT like fpgen:
 *  - the archive comes from the release pinned in MODEL_PIN (the twin of
 *    scripts/data/fpgen-model.json), never "the first release the API lists";
 *  - TLS is verified (Node's fetch always does), and the archive's size and
 *    sha256 are checked before a byte of it is extracted;
 *  - only the three expected members are written, by name, so a hostile
 *    archive cannot place files outside the data directory;
 *  - there is no five-week re-download: the model changes when the pin does.
 *
 * Layout of the data directory (compatible with scripts/pin-fpgen-model.py, so
 * CAMOUFOX_FPGEN_DATA may point at a pinned Python fpgen `data/` directory):
 *
 *   fingerprint-network.json.zst
 *   values.json.zst
 *   values.dat.zst
 *   values.dat          decompressed once on first load (~210 MB), then read
 *                       by offset -- fpgen does the same when values.dat exists
 *   .pinned-model       sha256 of the verified archive; written last
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { pipeline } from "node:stream/promises";
import * as zlib from "node:zlib";
import AdmZip from "adm-zip";
import { INSTALL_DIR } from "../paths.js";
import { BayesianNetwork } from "./bayesian-network.js";
import { ModelNotInstalled, ModelVerificationError } from "./exceptions.js";
import { MODEL_PIN, type ModelPin } from "./pin.js";
import { base85ToInt, parseOrdered } from "./pyjson.js";

export const STAMP_FILE = ".pinned-model";
export const NETWORK_ZST = "fingerprint-network.json.zst";
export const VALUES_JSON_ZST = "values.json.zst";
export const VALUES_DAT_ZST = "values.dat.zst";
export const VALUES_DAT = "values.dat";

/**
 * The model directory: $CAMOUFOX_FPGEN_DATA when set, otherwise `fpgen/` in
 * the Camoufox cache (next to the browsers, addons and fontconfig cache).
 */
export function modelDir(): string {
	const override = process.env.CAMOUFOX_FPGEN_DATA;
	if (override) return path.resolve(override);
	return path.join(INSTALL_DIR, "fpgen");
}

/** True when `dir` holds the pinned model (stamp matches, members present). */
export function isModelInstalled(
	dir: string = modelDir(),
	pin: ModelPin = MODEL_PIN,
): boolean {
	let stamp: string;
	try {
		stamp = fs.readFileSync(path.join(dir, STAMP_FILE), "utf-8").trim();
	} catch {
		return false;
	}
	if (stamp !== pin.sha256) return false;
	return pin.files.every((f) => fs.existsSync(path.join(dir, f)));
}

export interface EnsureModelOptions {
	/** Directory to install into / load from. Defaults to `modelDir()`. */
	dir?: string;
	/** Re-download even when the pinned model is already present. */
	force?: boolean;
	/** Override the fetch implementation (tests). */
	fetchImpl?: typeof fetch;
}

const inflight = new Map<string, Promise<string>>();

export const LOCK_DIR = ".install.lock";
/** A lock older than this was left by a process that died holding it. */
export const STALE_LOCK_MS = 10 * 60 * 1000;

/**
 * Run `fn` holding `dir`'s install lock, across processes. `inflight` only
 * dedupes within one process; several processes installing into an empty cache
 * at once (a worker pool on a fresh machine, or vitest's parallel files) would
 * otherwise each download the model, and one's install deleted the values.dat
 * another had just decompressed and was about to read. mkdir is atomic on every
 * platform, so the lock is a directory.
 */
export async function withInstallLock<T>(
	dir: string,
	fn: () => Promise<T>,
): Promise<T> {
	fs.mkdirSync(dir, { recursive: true });
	const lock = path.join(dir, LOCK_DIR);
	for (;;) {
		try {
			fs.mkdirSync(lock);
			break;
		} catch (e) {
			if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
			try {
				if (Date.now() - fs.statSync(lock).mtimeMs > STALE_LOCK_MS) {
					fs.rmSync(lock, { recursive: true, force: true });
					continue;
				}
			} catch {
				continue; // released between the mkdir and the stat
			}
			await new Promise((resolve) => setTimeout(resolve, 200));
		}
	}
	try {
		return await fn();
	} finally {
		fs.rmSync(lock, { recursive: true, force: true });
	}
}

/**
 * Make sure the pinned model is installed and values.dat is decompressed.
 * Downloads (TLS on, sha256-checked) only when it is missing. Returns the
 * model directory. Safe to call repeatedly and concurrently.
 */
export function ensureModel(options: EnsureModelOptions = {}): Promise<string> {
	const dir = path.resolve(options.dir ?? modelDir());
	const running = inflight.get(dir);
	if (running && !options.force) return running;
	const job = (async () => {
		// The unlocked check is the fast path for an installed model; the
		// locked one decides, since another process may have just installed it.
		if (!options.force && isModelInstalled(dir) && datIsReady(dir)) return dir;
		await withInstallLock(dir, async () => {
			if (options.force || !isModelInstalled(dir)) {
				const archive = await downloadArchive(MODEL_PIN, options.fetchImpl);
				installArchive(archive, dir, MODEL_PIN);
			}
			await decompressValuesDat(dir);
		});
		return dir;
	})();
	inflight.set(dir, job);
	job.catch(() => inflight.delete(dir));
	return job;
}

/** Download the pinned archive and verify its size and sha256. */
export async function downloadArchive(
	pin: ModelPin = MODEL_PIN,
	fetchImpl: typeof fetch = fetch,
	retries = 3,
): Promise<Buffer> {
	let lastError: unknown;
	for (let attempt = 0; attempt < retries; attempt++) {
		let response: Response;
		try {
			response = await fetchImpl(pin.url, {
				headers: { "User-Agent": "camoufox-js" },
				redirect: "follow",
				signal: AbortSignal.timeout(120_000),
			});
		} catch (e) {
			lastError = e;
			continue;
		}
		if (!response.ok) {
			lastError = new Error(
				`fpgen model download failed: HTTP ${response.status} for ${pin.url}`,
			);
			// 4xx will not get better by retrying.
			if (response.status >= 400 && response.status < 500) break;
			continue;
		}
		const buf = Buffer.from(await response.arrayBuffer());
		verifyArchive(buf, pin);
		return buf;
	}
	throw lastError instanceof Error
		? lastError
		: new Error(`fpgen model download failed: ${String(lastError)}`);
}

/** Throws ModelVerificationError unless `buf` is exactly the pinned archive. */
export function verifyArchive(buf: Buffer, pin: ModelPin = MODEL_PIN): void {
	if (pin.size && buf.length !== pin.size) {
		throw new ModelVerificationError(
			`fpgen model size mismatch: got ${buf.length}, expected ${pin.size}`,
		);
	}
	const got = createHash("sha256").update(buf).digest("hex");
	if (got !== pin.sha256) {
		throw new ModelVerificationError(
			`fpgen model sha256 mismatch:\n  got      ${got}\n  expected ${pin.sha256}`,
		);
	}
}

/** Write the pinned members of a verified archive into `dir`, stamp last. */
export function installArchive(
	archive: Buffer,
	dir: string,
	pin: ModelPin = MODEL_PIN,
): void {
	verifyArchive(archive, pin);
	fs.mkdirSync(dir, { recursive: true });
	let previous = "";
	try {
		previous = fs.readFileSync(path.join(dir, STAMP_FILE), "utf-8").trim();
	} catch {}
	// An interrupted install must not leave a stamp over a partial model.
	fs.rmSync(path.join(dir, STAMP_FILE), { force: true });
	// A values.dat decompressed from a DIFFERENT model would be trusted (its
	// size is all that is checked), so drop it -- but only then: reinstalling
	// the same model must not pull the file out from under a process reading it.
	if (previous !== pin.sha256) {
		fs.rmSync(path.join(dir, VALUES_DAT), { force: true });
	}
	const zip = new AdmZip(archive);
	for (const name of pin.files) {
		if (path.basename(name) !== name) {
			throw new ModelVerificationError(
				`unexpected member path in pin: ${name}`,
			);
		}
		const entry = zip.getEntry(name);
		if (!entry || entry.isDirectory) {
			throw new ModelVerificationError(
				`fpgen model archive is missing ${name}`,
			);
		}
		atomicWrite(path.join(dir, name), entry.getData());
	}
	fs.writeFileSync(path.join(dir, STAMP_FILE), `${pin.sha256}\n`);
}

function atomicWrite(target: string, data: Uint8Array): void {
	const tmp = `${target}.${process.pid}.${Date.now()}.tmp`;
	fs.writeFileSync(tmp, data);
	fs.renameSync(tmp, target);
}

/** Byte length values.dat must have: the end of the furthest slice. */
function expectedDatSize(valuePairs: readonly ValuePair[]): number {
	let end = 0;
	for (const [offset, length] of valuePairs) {
		if (offset + length > end) end = offset + length;
	}
	return end;
}

function datIsReady(dir: string): boolean {
	try {
		return datIsComplete(path.join(dir, VALUES_DAT), readValuePairs(dir));
	} catch {
		return false;
	}
}

function datIsComplete(
	datPath: string,
	valuePairs: readonly ValuePair[],
): boolean {
	try {
		return fs.statSync(datPath).size === expectedDatSize(valuePairs);
	} catch {
		return false;
	}
}

/** Stream-decompress values.dat.zst -> values.dat if it isn't there yet. */
async function decompressValuesDat(dir: string): Promise<void> {
	const datPath = path.join(dir, VALUES_DAT);
	const pairs = readValuePairs(dir);
	if (datIsComplete(datPath, pairs)) return;
	const tmp = `${datPath}.${process.pid}.${Date.now()}.tmp`;
	try {
		await pipeline(
			fs.createReadStream(path.join(dir, VALUES_DAT_ZST)),
			zlib.createZstdDecompress(),
			fs.createWriteStream(tmp),
		);
		fs.renameSync(tmp, datPath);
	} finally {
		fs.rmSync(tmp, { force: true });
	}
	if (!datIsComplete(datPath, pairs)) {
		throw new ModelVerificationError(
			`decompressed ${datPath} does not match values.json`,
		);
	}
}

function decompressValuesDatSync(
	dir: string,
	pairs: readonly ValuePair[],
): void {
	const datPath = path.join(dir, VALUES_DAT);
	if (datIsComplete(datPath, pairs)) return;
	const data = zlib.zstdDecompressSync(
		fs.readFileSync(path.join(dir, VALUES_DAT_ZST)),
	);
	atomicWrite(datPath, data);
	if (!datIsComplete(datPath, pairs)) {
		throw new ModelVerificationError(
			`decompressed ${datPath} does not match values.json`,
		);
	}
}

function readZstJson(file: string): unknown {
	return parseOrdered(
		zlib.zstdDecompressSync(fs.readFileSync(file)).toString("utf-8"),
	);
}

/** [byte offset, byte length] of each value in values.dat, by value id. */
export type ValuePair = readonly [offset: number, length: number];

function readValuePairs(dir: string): ValuePair[] {
	const json = readZstJson(path.join(dir, VALUES_JSON_ZST));
	if (!(json instanceof Map)) {
		throw new ModelVerificationError("values.json is not an object");
	}
	// VALUE_PAIRS = list(values_json.items()) -- document order is the id.
	const pairs: ValuePair[] = [];
	for (const [hexOffset, length] of json as Map<string, number>) {
		pairs.push([Number.parseInt(hexOffset, 16), length]);
	}
	return pairs;
}

/**
 * The loaded model: the Bayesian network plus the value store it indexes into.
 * One per data directory, loaded on first use (fpgen loads it at import).
 */
export class FpgenModel {
	readonly network: BayesianNetwork;
	readonly valuePairs: readonly ValuePair[];
	readonly datPath: string;
	/** Held open for the model's lifetime: one open per lookup was a syscall
	 * per call, and a path reopened each time fails if the file is replaced. */
	private fd: number | null = null;

	constructor(readonly dir: string) {
		this.valuePairs = readValuePairs(dir);
		this.datPath = path.join(dir, VALUES_DAT);
		decompressValuesDatSync(dir, this.valuePairs);
		this.network = new BayesianNetwork(
			readZstJson(path.join(dir, NETWORK_ZST)),
			this,
		);
	}

	/** unpacker.lookup_value: the raw JSON text stored for a value id. */
	lookupValue(index: string): string {
		return this.lookupValueList([index])[0];
	}

	/**
	 * unpacker.lookup_value_list: raw JSON text for each id, in input order.
	 * Reads in ascending offset order, as fpgen does.
	 */
	lookupValueList(indexList: Iterable<string>): string[] {
		const ids = [...indexList];
		const out = new Array<string>(ids.length);
		const sorted = ids
			.map((id, n) => [base85ToInt(id), n] as const)
			.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
		if (this.fd === null) this.fd = fs.openSync(this.datPath, "r");
		const fd = this.fd;
		for (const [index, n] of sorted) {
			const pair = this.valuePairs[index];
			if (pair === undefined) {
				throw new RangeError(`list index out of range: value id ${index}`);
			}
			const [offset, length] = pair;
			const buf = Buffer.allocUnsafe(length);
			let read = 0;
			while (read < length) {
				const got = fs.readSync(fd, buf, read, length - read, offset + read);
				if (got === 0) break;
				read += got;
			}
			out[n] = buf.toString("utf-8", 0, read);
		}
		return out;
	}

	/** Release the values.dat handle. The model reopens it on next use. */
	close(): void {
		if (this.fd !== null) fs.closeSync(this.fd);
		this.fd = null;
	}
}

const loaded = new Map<string, FpgenModel>();

/**
 * The model for `dir` (default `modelDir()`), loading it on first call.
 * Synchronous: throws ModelNotInstalled when the pinned model is not on disk --
 * `await ensureModel()` first.
 */
export function getModel(dir: string = modelDir()): FpgenModel {
	const key = path.resolve(dir);
	let model = loaded.get(key);
	if (model) return model;
	if (!isModelInstalled(key)) {
		throw new ModelNotInstalled(
			`The fpgen model (${MODEL_PIN.tag}) is not installed in ${key}. ` +
				"Call `await ensureModel()` (camoufox/fpgen) before generating fingerprints.",
		);
	}
	model = new FpgenModel(key);
	loaded.set(key, model);
	return model;
}

/** Drop loaded models (tests, or after changing CAMOUFOX_FPGEN_DATA). */
export function resetModelCache(): void {
	for (const model of loaded.values()) model.close();
	loaded.clear();
}
