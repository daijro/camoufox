import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { PyFloat } from "../src/pycompat.js";
import {
	checkValidOs,
	configJson,
	determineUaOs,
	getEnvVars,
	getTargetOs,
	isDomainSet,
	mergeInto,
	pyJsonDumpsAscii,
	pyTypeName,
	setInto,
	spoofsWindowDimensions,
	validateType,
} from "../src/utils.js";

const BUNDLE_EXE = path.join(
	path.dirname(fileURLToPath(import.meta.url)),
	"fixtures",
	"launch",
	"bundle",
	"camoufox-bin",
);

const WINDOWS_UA =
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0";
const MAC_UA =
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0";
const LINUX_UA =
	"Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0";

describe("determineUaOs", () => {
	it("maps each supported UA to its short OS name", () => {
		expect(determineUaOs(WINDOWS_UA)).toBe("win");
		expect(determineUaOs(MAC_UA)).toBe("mac");
		expect(determineUaOs(LINUX_UA)).toBe("lin");
	});

	it("falls back to lin for an unparseable UA, as the Python twin does", () => {
		// Python's ua_parser answers "Other" rather than nothing, so its `raise`
		// never fires. Throwing here instead would make
		// `config: {"navigator.userAgent": ...}` launch under one launcher and
		// hard-error under the other.
		expect(determineUaOs("X")).toBe("lin");
		expect(determineUaOs("")).toBe("lin");
	});
});

describe("getTargetOs", () => {
	it("derives the OS from the config's user agent", () => {
		expect(getTargetOs({ "navigator.userAgent": WINDOWS_UA })).toBe("win");
	});
});

describe("checkValidOs", () => {
	it("accepts the supported OS names, individually and as a list", () => {
		expect(() => checkValidOs("windows")).not.toThrow();
		expect(() => checkValidOs(["macos", "linux"])).not.toThrow();
	});

	it("rejects unsupported and non-lowercase names", () => {
		expect(() => checkValidOs("Windows")).toThrow(/lowercase/);
		expect(() => checkValidOs("solaris")).toThrow(/does not support/);
	});
});

describe("validateType", () => {
	it("matches properties.json type names to JS values", () => {
		expect(validateType("x", "str")).toBe(true);
		expect(validateType(1, "str")).toBe(false);
		expect(validateType(1, "int")).toBe(true);
		expect(validateType(1.5, "int")).toBe(false);
		expect(validateType(-1, "uint")).toBe(false);
		expect(validateType(1.5, "double")).toBe(true);
		expect(validateType(true, "bool")).toBe(true);
		expect(validateType([], "array")).toBe(true);
		expect(validateType({}, "dict")).toBe(true);
		expect(validateType([], "dict")).toBe(false);
		expect(validateType("x", "unknown-type")).toBe(false);
		// Python's bool is an int, so it passes the numeric checks there too.
		expect(validateType(true, "uint")).toBe(true);
		// An integral Python float passes int/uint (float.is_integer()).
		expect(validateType(new PyFloat(2), "uint")).toBe(true);
		expect(validateType(new PyFloat(2), "str")).toBe(false);
	});
});

describe("isDomainSet", () => {
	it("matches exact keys and dotted/colon prefixes", () => {
		const config = { "navigator.platform": "Win32", "locale:region": "US" };
		expect(isDomainSet(config, "navigator.platform")).toBe(true);
		expect(isDomainSet(config, "navigator.")).toBe(true);
		expect(isDomainSet(config, "locale:")).toBe(true);
		expect(isDomainSet(config, "screen.")).toBe(false);
		expect(isDomainSet(config, "timezone")).toBe(false);
	});
});

describe("mergeInto / setInto", () => {
	it("never overwrites an existing key", () => {
		const target: Record<string, unknown> = { a: 1 };
		mergeInto(target, { a: 2, b: 3 });
		expect(target).toEqual({ a: 1, b: 3 });

		setInto(target, "a", 9);
		setInto(target, "c", 9);
		expect(target).toEqual({ a: 1, b: 3, c: 9 });
	});
});

describe("getEnvVars", () => {
	it("chunks the config across CAMOU_CONFIG_<n> in index order", () => {
		// A payload comfortably larger than the 32767-char POSIX chunk size.
		const config = { "navigator.userAgent": "x".repeat(70_000) };
		const env = getEnvVars(config, "win", BUNDLE_EXE);

		const keys = Object.keys(env)
			.filter((k) => k.startsWith("CAMOU_CONFIG_"))
			.sort((a, b) => Number(a.split("_").pop()) - Number(b.split("_").pop()));
		expect(keys.length).toBeGreaterThan(1);
		expect(keys[0]).toBe("CAMOU_CONFIG_1");

		const reassembled = keys.map((k) => env[k]).join("");
		expect(JSON.parse(reassembled)).toEqual(config);
	});
});

describe("spoofsWindowDimensions", () => {
	it("reassembles chunks before looking for a window dimension key", () => {
		const config = { "window.outerWidth": 1280 };
		expect(
			spoofsWindowDimensions({ env: getEnvVars(config, "win", BUNDLE_EXE) }),
		).toBe(true);
	});

	it("is false when nothing spoofs a window dimension", () => {
		expect(
			spoofsWindowDimensions({
				env: getEnvVars({ "screen.width": 1920 }, "win", BUNDLE_EXE),
			}),
		).toBe(false);
		expect(spoofsWindowDimensions({})).toBe(false);
	});

	it("finds a key that straddles a chunk boundary", () => {
		// Pad so "window.outerHeight" is split across two CAMOU_CONFIG_<n> vars.
		const config = {
			pad: "x".repeat(32_750),
			"window.outerHeight": 720,
		};
		const env = getEnvVars(config, "win", BUNDLE_EXE);
		expect(
			Object.keys(env).filter((k) => k.startsWith("CAMOU_CONFIG_")).length,
		).toBeGreaterThan(1);
		expect(spoofsWindowDimensions({ env })).toBe(true);
	});
});

describe("Python-compatible serialisation", () => {
	it("chunks by code point, as Python slices a str", () => {
		// 32767 emoji: one chunk in Python (code points), two UTF-16 halves each.
		const config = { v: "\u{1F600}".repeat(40_000) };
		const env = getEnvVars(config, "win", BUNDLE_EXE);
		const chunks = Object.keys(env).filter((k) =>
			k.startsWith("CAMOU_CONFIG_"),
		);
		const blob = JSON.stringify(config);
		expect(chunks).toHaveLength(Math.ceil(Array.from(blob).length / 32767));
		expect(Array.from(String(env.CAMOU_CONFIG_1))).toHaveLength(32767);
	});

	it("writes a PyFloat with its .0 and a bigint exactly", () => {
		expect(configJson({ a: new PyFloat(2), b: 2, c: 1.5, d: 2n ** 64n })).toBe(
			'{"a":2.0,"b":2,"c":1.5,"d":18446744073709551616}',
		);
	});

	it("names types the way Python does in its errors", () => {
		expect(pyTypeName(1)).toBe("int");
		expect(pyTypeName(1.5)).toBe("float");
		expect(pyTypeName(new PyFloat(1))).toBe("float");
		expect(pyTypeName(true)).toBe("bool");
		expect(pyTypeName(null)).toBe("NoneType");
		expect(pyTypeName([])).toBe("list");
		expect(pyTypeName({})).toBe("dict");
	});

	it("json.dumps(ensure_ascii=True) for the prefs", () => {
		expect(pyJsonDumpsAscii({ a: "é\u007f", b: 1e-5, c: [true, null] })).toBe(
			'{"a":"\\u00e9\\u007f","b":1e-05,"c":[true,null]}',
		);
	});
});
