/**
 * Python-semantics helpers for the fpgen port (scrapfly/fingerprint-generator,
 * Apache-2.0; see ./NOTICE).
 *
 * fpgen leans on three Python behaviours JavaScript does not share, and each
 * one changes results if it is dropped:
 *
 *  1. dict order. Every probability table is a dict keyed by base85 value ids,
 *     and 5.5k of those ids ("0", "12", ...) look like array indices, which a JS
 *     object silently moves to the front. The order decides which value a
 *     cumulative draw lands on and how the beam breaks ties, so the network is
 *     parsed into Maps (`parseOrdered`).
 *  2. int vs float. `query()` groups values by Python type and sorts each group,
 *     so 1.0 and 1 land in different places. `parsePyTyped` keeps floats
 *     wrapped as PyFloat until the grouping is done.
 *  3. `==`. Nested conditions compare parsed values with Python equality, where
 *     1 == 1.0 == True and dicts ignore key order (`pyEquals`).
 */

import { ValueError } from "./exceptions.js";

/** Marks a Python float through `query()`'s type grouping. */
export class PyFloat {
	constructor(readonly value: number) {}
}

const KEY_TOKEN = /"(?:[^"\\]|\\.)*"(\s*:)?/g;

/**
 * JSON.parse, but every object becomes a Map whose iteration order is the
 * document order (the order Python's dict would have).
 */
export function parseOrdered(text: string): unknown {
	// Prefix every object key with U+0001 (written as its JSON escape: a raw
	// control character is not valid inside a JSON string) so none is integer-like, which makes
	// the native parser keep insertion order; the reviver strips it again. The
	// regex consumes whole string tokens, so a quote or colon inside a string
	// can never be mistaken for a key.
	const marked = text.replace(KEY_TOKEN, (tok, colon: string | undefined) =>
		colon === undefined ? tok : `"\\u0001${tok.slice(1)}`,
	);
	return JSON.parse(marked, (_key, value) => {
		if (value === null || typeof value !== "object" || Array.isArray(value)) {
			return value;
		}
		const map = new Map<string, unknown>();
		for (const k of Object.keys(value)) {
			map.set(k.slice(1), value[k]);
		}
		return map;
	});
}

const TYPED_TOKEN =
	/"(?:[^"\\]|\\.)*"|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
const FLOAT_MARK = "\u0001pyfloat";
const FLOAT_MARK_JSON = "\\u0001pyfloat";

/**
 * JSON.parse that keeps Python's int/float distinction: a number token written
 * with a fraction or exponent (what Python's json/orjson emit for a float) comes
 * back as a PyFloat. Use `unwrapPy` to get plain values back.
 */
export function parsePyTyped(text: string): unknown {
	const marked = text.replace(TYPED_TOKEN, (tok) =>
		tok[0] === '"' || !/[.eE]/.test(tok)
			? tok
			: `{"${FLOAT_MARK_JSON}":${tok}}`,
	);
	return JSON.parse(marked, (_key, value) => {
		if (
			value !== null &&
			typeof value === "object" &&
			!Array.isArray(value) &&
			FLOAT_MARK in value
		) {
			return new PyFloat(value[FLOAT_MARK]);
		}
		return value;
	});
}

/** Replace every PyFloat in a structure with its number. */
export function unwrapPy(value: unknown): unknown {
	if (value instanceof PyFloat) return value.value;
	if (Array.isArray(value)) return value.map(unwrapPy);
	if (isPlainObject(value)) {
		const out: Record<string, unknown> = {};
		for (const [k, v] of Object.entries(value)) out[k] = unwrapPy(v);
		return out;
	}
	return value;
}

export function isPlainObject(value: unknown): value is Record<string, any> {
	if (value === null || typeof value !== "object") return false;
	const proto = Object.getPrototypeOf(value);
	return proto === Object.prototype || proto === null;
}

function pyNumber(value: unknown): number | undefined {
	if (typeof value === "number") return value;
	if (typeof value === "boolean") return value ? 1 : 0;
	if (value instanceof PyFloat) return value.value;
	return undefined;
}

/** Python `==` over JSON-shaped values (1 == 1.0 == True, dicts unordered). */
export function pyEquals(a: unknown, b: unknown): boolean {
	const na = pyNumber(a);
	const nb = pyNumber(b);
	if (na !== undefined || nb !== undefined) return na === nb;
	if (a === null || b === null) return a === b;
	if (typeof a === "string" || typeof b === "string") return a === b;
	if (Array.isArray(a) || Array.isArray(b)) {
		if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) {
			return false;
		}
		return a.every((v, i) => pyEquals(v, b[i]));
	}
	if (isPlainObject(a) && isPlainObject(b)) {
		const ka = Object.keys(a);
		if (ka.length !== Object.keys(b).length) return false;
		return ka.every((k) => Object.hasOwn(b, k) && pyEquals(a[k], b[k]));
	}
	return a === b;
}

/**
 * Python's str.casefold(). toLowerCase() agrees with it everywhere except the
 * handful of characters whose full case folding expands or differs; those are
 * mapped explicitly. (Every value in the model is ASCII, so this only matters
 * for what a caller types.)
 */
export function casefold(s: string): string {
	const lower = s.toLowerCase();
	// biome-ignore lint/suspicious/noControlCharactersInRegex: ASCII fast path
	if (/^[\x00-\x7f]*$/.test(lower)) return lower;
	return lower
		.replace(/ß|ẞ/g, "ss")
		.replace(/ς/g, "σ")
		.replace(/ſ/g, "s")
		.replace(/ﬀ/g, "ff")
		.replace(/ﬁ/g, "fi")
		.replace(/ﬂ/g, "fl")
		.replace(/ﬃ/g, "ffi")
		.replace(/ﬄ/g, "ffl")
		.replace(/ﬅ|ﬆ/g, "st");
}

/**
 * orjson.dumps(value).decode() for a condition value. JSON.stringify writes
 * the same compact form; the one thing it cannot write is `1.0`, because JS
 * has no separate float (build_evidence compensates, see utils.ts).
 */
export function pyDumps(value: unknown): string {
	if (typeof value === "function") {
		// orjson.JSONDecodeError is a TypeError subclass.
		throw new TypeError("Type is not JSON serializable: function");
	}
	const out = JSON.stringify(value);
	if (out === undefined) {
		throw new TypeError(`Type is not JSON serializable: ${typeof value}`);
	}
	return out;
}

const B85_ALPHABET =
	"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~";
const B85_DECODE = new Map<string, number>(
	[...B85_ALPHABET].map((c, i) => [c, i]),
);

/** int.from_bytes(base64.b85decode(s), 'big') -- unpacker.base85_to_int. */
export function base85ToInt(s: string): number {
	const padding = (5 - (s.length % 5)) % 5;
	const padded = s + "~".repeat(padding);
	const bytes: number[] = [];
	for (let i = 0; i < padded.length; i += 5) {
		let acc = 0;
		for (let j = i; j < i + 5; j++) {
			const d = B85_DECODE.get(padded[j]);
			if (d === undefined) {
				throw new ValueError(`bad base85 character at position ${j}`);
			}
			acc = acc * 85 + d;
		}
		if (acc > 0xffffffff) {
			throw new ValueError(`base85 overflow in hunk starting at byte ${i}`);
		}
		bytes.push(
			(acc >>> 24) & 0xff,
			(acc >>> 16) & 0xff,
			(acc >>> 8) & 0xff,
			acc & 0xff,
		);
	}
	if (padding) bytes.length -= padding;
	let n = 0;
	for (const b of bytes) {
		n = n * 256 + b;
		if (n > Number.MAX_SAFE_INTEGER) {
			throw new ValueError(`base85 value too large: ${s}`);
		}
	}
	return n;
}

/** Python's default ordering for a homogeneous group (str by code point). */
export function pyCompare(a: unknown, b: unknown): number {
	const na = pyNumber(a);
	const nb = pyNumber(b);
	if (na !== undefined && nb !== undefined) return na - nb;
	if (typeof a === "string" && typeof b === "string") {
		// Code-point order, not UTF-16 code-unit order.
		const ia = a[Symbol.iterator]();
		const ib = b[Symbol.iterator]();
		for (;;) {
			const x = ia.next();
			const y = ib.next();
			if (x.done || y.done) return x.done ? (y.done ? 0 : -1) : 1;
			const cx = x.value.codePointAt(0) as number;
			const cy = y.value.codePointAt(0) as number;
			if (cx !== cy) return cx - cy;
		}
	}
	return 0;
}

/** Python's `type(x).__name__` for a (PyFloat-tagged) JSON value. */
export function pyTypeName(value: unknown): string {
	if (value === null) return "NoneType";
	if (value instanceof PyFloat) return "float";
	if (typeof value === "boolean") return "bool";
	if (typeof value === "number")
		return Number.isInteger(value) ? "int" : "float";
	if (typeof value === "string") return "str";
	if (Array.isArray(value)) return "list";
	return "dict";
}
