/**
 * The handful of CPython / orjson behaviours the identity layer has to
 * reproduce bit-for-bit so that the same inputs yield the same identity in the
 * Python and TypeScript launchers: orjson's JSON bytes (hashed by
 * identity_salt), str() of a value (hashed by identity_seed), zlib.crc32,
 * code-point string ordering, and the float summation builtin sum() uses.
 *
 * JavaScript has one number type where Python has two, so `1.0` and `1` are
 * the same value here. Where the difference reaches a hash, wrap the float in
 * {@link PyFloat}, or read the JSON with {@link parsePyJson}, which keeps the
 * distinction (and keeps integers above 2**53 exact as bigint).
 */

import { FileNotFoundError } from "./exceptions.js";

/** A Python float whose value happens to be integral (1.0, 3.4e38...). */
export class PyFloat {
	constructor(public readonly value: number) {}

	valueOf(): number {
		return this.value;
	}

	toJSON(): number {
		return this.value;
	}

	toString(): string {
		return formatPyFloatRepr(this.value);
	}
}

/** Number of a value that may be a PyFloat. */
export function num(value: unknown): number {
	return value instanceof PyFloat ? value.value : (value as number);
}

/** Whether `value` is a Python int (bool counts, as in Python). */
export function isPyInt(value: unknown): boolean {
	return (
		typeof value === "bigint" ||
		typeof value === "boolean" ||
		(typeof value === "number" && Number.isSafeInteger(value))
	);
}

/**
 * JSON.parse that keeps what Python's json.loads would: `1.0` stays a float
 * (a {@link PyFloat} when integral) and an integer beyond 2**53 stays exact
 * (a bigint).
 */
export function parsePyJson(text: string): any {
	return JSON.parse(text, function (
		this: any,
		_key: string,
		value: any,
		context?: { source?: string },
	) {
		if (typeof value !== "number" || !context?.source) return value;
		const src = context.source;
		const isFloat = /[.eE]/.test(src);
		if (!isFloat) {
			return Number.isSafeInteger(value) ? value : BigInt(src);
		}
		return Number.isSafeInteger(value) ? new PyFloat(value) : value;
	} as any);
}

/** Shortest round-trip digits and decimal exponent of a finite, non-zero x. */
function shortestDigits(x: number): { digits: string; exp: number } {
	const [mantissa, exponent] = Math.abs(x).toExponential().split("e");
	return { digits: mantissa.replace(".", ""), exp: Number(exponent) };
}

function fixedNotation(digits: string, exp: number): string {
	if (exp >= 0) {
		if (digits.length <= exp + 1) {
			return `${digits}${"0".repeat(exp + 1 - digits.length)}.0`;
		}
		return `${digits.slice(0, exp + 1)}.${digits.slice(exp + 1)}`;
	}
	return `0.${"0".repeat(-exp - 1)}${digits}`;
}

function sciMantissa(digits: string): string {
	return digits.length === 1 ? digits : `${digits[0]}.${digits.slice(1)}`;
}

/** A float exactly as orjson serializes it. */
export function formatOrjsonFloat(x: number): string {
	if (!Number.isFinite(x)) return "null";
	if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
	const sign = x < 0 ? "-" : "";
	const { digits, exp } = shortestDigits(x);
	if (exp >= -5 && exp < 16) return sign + fixedNotation(digits, exp);
	return `${sign}${sciMantissa(digits)}e${exp < 0 ? "-" : "+"}${Math.abs(exp)}`;
}

/** repr(float) / str(float) in CPython. */
export function formatPyFloatRepr(x: number): string {
	if (Number.isNaN(x)) return "nan";
	if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
	if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
	const sign = x < 0 ? "-" : "";
	const { digits, exp } = shortestDigits(x);
	if (exp >= -4 && exp < 16) return sign + fixedNotation(digits, exp);
	const e = Math.abs(exp).toString().padStart(2, "0");
	return `${sign}${sciMantissa(digits)}e${exp < 0 ? "-" : "+"}${e}`;
}

/** Compare two strings by code point, as Python (and UTF-8 bytes) order them. */
export function comparePyStr(a: string, b: string): number {
	if (a === b) return 0;
	const n = Math.min(a.length, b.length);
	for (let i = 0; i < n; i++) {
		const ca = a.charCodeAt(i);
		const cb = b.charCodeAt(i);
		if (ca === cb) continue;
		// Surrogates (0xD800-0xDFFF) encode code points above every other
		// BMP unit, so only the surrogate-vs-high-BMP case reorders.
		const sa = ca >= 0xd800 && ca <= 0xdfff;
		const sb = cb >= 0xd800 && cb <= 0xdfff;
		if (sa !== sb) {
			if (sa) return cb >= 0xe000 ? 1 : ca - cb;
			return ca >= 0xe000 ? -1 : ca - cb;
		}
		return ca - cb;
	}
	return a.length - b.length;
}

/** Python truthiness of a JSON-like value. */
export function pyTruthy(value: unknown): boolean {
	if (value === null || value === undefined) return false;
	if (value instanceof PyFloat) return value.value !== 0;
	if (typeof value === "number") return value !== 0;
	if (typeof value === "bigint") return value !== 0n;
	if (typeof value === "string") return value.length > 0;
	if (typeof value === "boolean") return value;
	if (Array.isArray(value)) return value.length > 0;
	if (value instanceof Map || value instanceof Set) return value.size > 0;
	if (typeof value === "object") return Object.keys(value).length > 0;
	return true;
}

const NON_PRINTABLE = /[\p{C}\p{Z}]/u;

/** repr() of a str. */
export function pyStrRepr(s: string): string {
	const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
	let out = quote;
	for (const ch of s) {
		const cp = ch.codePointAt(0) as number;
		if (ch === quote || ch === "\\") out += `\\${ch}`;
		else if (ch === "\t") out += "\\t";
		else if (ch === "\n") out += "\\n";
		else if (ch === "\r") out += "\\r";
		else if (cp < 0x20 || cp === 0x7f)
			out += `\\x${cp.toString(16).padStart(2, "0")}`;
		else if (ch !== " " && NON_PRINTABLE.test(ch)) {
			if (cp <= 0xff) out += `\\x${cp.toString(16).padStart(2, "0")}`;
			else if (cp <= 0xffff) out += `\\u${cp.toString(16).padStart(4, "0")}`;
			else out += `\\U${cp.toString(16).padStart(8, "0")}`;
		} else out += ch;
	}
	return out + quote;
}

function pyNumberStr(value: number): string {
	if (Number.isSafeInteger(value)) return String(value);
	return formatPyFloatRepr(value);
}

/** repr() of a JSON-like value. */
export function pyRepr(value: unknown): string {
	if (typeof value === "string") return pyStrRepr(value);
	if (Array.isArray(value)) return `[${value.map(pyRepr).join(", ")}]`;
	if (value instanceof PyFloat) return formatPyFloatRepr(value.value);
	if (value !== null && typeof value === "object") {
		const entries =
			value instanceof Map ? [...value.entries()] : Object.entries(value);
		return `{${entries.map(([k, v]) => `${pyRepr(k)}: ${pyRepr(v)}`).join(", ")}}`;
	}
	return pyStr(value);
}

/** str() of a JSON-like value. */
export function pyStr(value: unknown): string {
	if (value === null || value === undefined) return "None";
	if (value === true) return "True";
	if (value === false) return "False";
	if (typeof value === "string") return value;
	if (typeof value === "bigint") return value.toString();
	if (typeof value === "number") return pyNumberStr(value);
	if (value instanceof PyFloat) return formatPyFloatRepr(value.value);
	return pyRepr(value);
}

function orjsonString(s: string): string {
	let out = '"';
	for (let i = 0; i < s.length; i++) {
		const c = s.charCodeAt(i);
		if (c === 0x22) out += '\\"';
		else if (c === 0x5c) out += "\\\\";
		else if (c < 0x20) {
			switch (c) {
				case 0x08:
					out += "\\b";
					break;
				case 0x09:
					out += "\\t";
					break;
				case 0x0a:
					out += "\\n";
					break;
				case 0x0c:
					out += "\\f";
					break;
				case 0x0d:
					out += "\\r";
					break;
				default:
					out += `\\u${c.toString(16).padStart(4, "0")}`;
			}
		} else out += s[i];
	}
	return `${out}"`;
}

function orjsonKey(key: unknown): string {
	if (typeof key === "string") return key;
	if (key === null || key === undefined) return "null";
	if (typeof key === "boolean") return key ? "true" : "false";
	if (typeof key === "bigint") return key.toString();
	if (key instanceof PyFloat) return formatOrjsonFloat(key.value);
	if (typeof key === "number") {
		return Number.isSafeInteger(key) ? String(key) : formatOrjsonFloat(key);
	}
	return pyStr(key);
}

/**
 * orjson.dumps(value, option=OPT_SORT_KEYS | OPT_NON_STR_KEYS, default=str),
 * as a string (its UTF-8 encoding is orjson's bytes).
 *
 * Plain numbers that are safe integers serialize as Python ints, every other
 * number as a float; use {@link PyFloat} for an integral float and bigint for
 * an integer beyond 2**53. An object with a `toPyDict()` method (the TS twin
 * of a dataclass) serializes as that dict.
 */
export function orjsonDumps(value: unknown, sortKeys = true): string {
	if (value === null || value === undefined) return "null";
	if (value === true) return "true";
	if (value === false) return "false";
	if (typeof value === "string") return orjsonString(value);
	if (typeof value === "bigint") return value.toString();
	if (typeof value === "number") {
		return Number.isSafeInteger(value)
			? String(value)
			: formatOrjsonFloat(value);
	}
	if (value instanceof PyFloat) return formatOrjsonFloat(value.value);
	if (Array.isArray(value)) {
		return `[${value.map((v) => orjsonDumps(v, sortKeys)).join(",")}]`;
	}
	if (typeof value === "object") {
		const withDict = value as { toPyDict?: () => unknown };
		if (typeof withDict.toPyDict === "function") {
			return orjsonDumps(withDict.toPyDict(), sortKeys);
		}
		if (value instanceof Set) {
			return orjsonString(pyStr([...value]));
		}
		let entries: Array<[string, unknown]>;
		if (value instanceof Map) {
			entries = [...value.entries()].map(([k, v]) => [orjsonKey(k), v]);
		} else if (
			Object.getPrototypeOf(value) === Object.prototype ||
			Object.getPrototypeOf(value) === null
		) {
			entries = Object.entries(value);
		} else {
			// default=str
			return orjsonString(String(value));
		}
		if (sortKeys) entries.sort((a, b) => comparePyStr(a[0], b[0]));
		return `{${entries.map(([k, v]) => `${orjsonString(k)}:${orjsonDumps(v, sortKeys)}`).join(",")}}`;
	}
	return orjsonString(String(value));
}

/**
 * sum() over floats, as CPython 3.12+ computes it (Neumaier-compensated).
 * CPython 3.10/3.11 fold left without compensation; the two differ only in
 * the last bit, and only for sums that lose precision.
 */
export function pySumFloats(values: Iterable<number>): number {
	let started = false;
	let f = 0;
	let c = 0;
	for (const x of values) {
		if (!started) {
			// int 0 start + first float: a plain add
			f = 0 + x;
			started = true;
			continue;
		}
		const t = f + x;
		if (Math.abs(f) >= Math.abs(x)) c += f - t + x;
		else c += x - t + f;
		f = t;
	}
	if (c !== 0 && Number.isFinite(c)) f += c;
	return f;
}

/**
 * sum() over a mix of ints and floats, as CPython 3.14 computes it: ints add
 * exactly until the first float, which is added plainly; after that every item
 * is Neumaier-compensated. (3.12/3.13 add those later ints without
 * compensation and 3.10/3.11 compensate nothing, so a sum that loses
 * precision can differ in its last bit there.) A safe
 * integer number counts as an int here, anything else (or a PyFloat) as a
 * float. Returns a number, or a bigint when every item was an int that only
 * a bigint holds exactly.
 */
export function pySum(values: Iterable<unknown>): number | bigint {
	let i: bigint | null = 0n;
	let f = 0;
	let c = 0;
	for (const v of values) {
		const isInt =
			typeof v === "bigint" ||
			typeof v === "boolean" ||
			(typeof v === "number" && Number.isSafeInteger(v));
		if (i !== null) {
			if (isInt) {
				i += typeof v === "bigint" ? v : BigInt(Number(v));
				continue;
			}
			f = Number(i) + num(v);
			i = null;
			continue;
		}
		const x = isInt ? Number(v) : num(v);
		const t = f + x;
		if (Math.abs(f) >= Math.abs(x)) c += f - t + x;
		else c += x - t + f;
		f = t;
	}
	if (i !== null) return Number.isSafeInteger(Number(i)) ? Number(i) : i;
	if (c !== 0 && Number.isFinite(c)) f += c;
	return f;
}

let CRC_TABLE: Uint32Array | null = null;

/** zlib.crc32. */
export function crc32(data: Uint8Array | string): number {
	if (!CRC_TABLE) {
		CRC_TABLE = new Uint32Array(256);
		for (let n = 0; n < 256; n++) {
			let c = n;
			for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
			CRC_TABLE[n] = c >>> 0;
		}
	}
	const bytes =
		typeof data === "string" ? new TextEncoder().encode(data) : data;
	let crc = 0xffffffff;
	for (let i = 0; i < bytes.length; i++) {
		crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
	}
	return (crc ^ 0xffffffff) >>> 0;
}

/** Python's OSError, for failures Node does not raise as a system error. */
export class OSError extends Error {
	name = "OSError";
}

/** Python's ValueError. */
export class ValueError extends Error {
	name = "ValueError";
}

/** Python's KeyError. */
export class KeyError extends Error {
	name = "KeyError";
}

const PY_ERROR_TESTS = {
	// Node's system errors (fs, net) carry a string code and a numeric errno;
	// FileNotFoundError is an OSError in Python.
	OSError: (e: unknown) =>
		e instanceof OSError ||
		e instanceof FileNotFoundError ||
		(e instanceof Error &&
			typeof (e as NodeJS.ErrnoException).code === "string" &&
			typeof (e as NodeJS.ErrnoException).errno === "number"),
	// JSON.parse's SyntaxError is json.JSONDecodeError, a ValueError.
	ValueError: (e: unknown) =>
		e instanceof ValueError || e instanceof SyntaxError,
	KeyError: (e: unknown) => e instanceof KeyError,
};

/** Whether `except (<kinds>)` in the Python twin would catch `error`. */
export function isPyError(
	error: unknown,
	...kinds: Array<keyof typeof PY_ERROR_TESTS>
): boolean {
	return kinds.some((kind) => PY_ERROR_TESTS[kind](error));
}
