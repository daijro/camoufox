/**
 * fpgen model handling -- the part deliberately NOT ported from fpgen: the pin,
 * the sha256 gate, safe extraction, where the files live -- plus the Python
 * semantics helpers and a few behaviours worth pinning down explicitly.
 */

import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import AdmZip from "adm-zip";
import { afterEach, describe, expect, it } from "vitest";
import {
	ensureModel,
	Generator,
	getModel,
	InvalidConstraints,
	installArchive,
	isModelInstalled,
	MODEL_PIN,
	ModelNotInstalled,
	type ModelPin,
	ModelVerificationError,
	modelDir,
	query,
	verifyArchive,
} from "../src/fpgen/index.js";
import {
	LOCK_DIR,
	STALE_LOCK_MS,
	withInstallLock,
} from "../src/fpgen/model.js";
import {
	casefold,
	PyFloat,
	parseOrdered,
	parsePyTyped,
	pyEquals,
} from "../src/fpgen/pyjson.js";
import { MODEL } from "./fpgen-setup.js";
import { prerequisite } from "./prereq.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_PIN = path.resolve(HERE, "../../scripts/data/fpgen-model.json");

const tmpDirs: string[] = [];
function tmpDir(): string {
	const d = fs.mkdtempSync(path.join(os.tmpdir(), "fpgen-test-"));
	tmpDirs.push(d);
	return d;
}
afterEach(() => {
	for (const d of tmpDirs.splice(0))
		fs.rmSync(d, { recursive: true, force: true });
});

function pinFor(buf: Buffer, files: string[]): ModelPin {
	return {
		...MODEL_PIN,
		size: buf.length,
		sha256: createHash("sha256").update(buf).digest("hex"),
		files,
	};
}

describe("fpgen model pin", () => {
	it.skipIf(!prerequisite("repo-pin", fs.existsSync(REPO_PIN), REPO_PIN))(
		"matches scripts/data/fpgen-model.json (bump both together)",
		() => {
			const repo = JSON.parse(fs.readFileSync(REPO_PIN, "utf-8"));
			const { note: _note, ...fields } = repo;
			expect({ ...MODEL_PIN, files: [...MODEL_PIN.files] }).toEqual(fields);
		},
	);

	it("downloads over https from the pinned tag", () => {
		expect(MODEL_PIN.url.startsWith("https://github.com/")).toBe(true);
		expect(MODEL_PIN.url).toContain(`/download/${MODEL_PIN.tag}/`);
	});

	it("rejects an archive of the wrong size or digest", () => {
		expect(() => verifyArchive(Buffer.from("nope"))).toThrow(
			ModelVerificationError,
		);
		const sameSize = Buffer.alloc(MODEL_PIN.size);
		expect(() => verifyArchive(sameSize)).toThrow(/sha256 mismatch/);
	});

	it("ensureModel refuses a tampered download and installs nothing", async () => {
		const dir = tmpDir();
		const evil = Buffer.alloc(MODEL_PIN.size, 7);
		const fetchImpl = (async () =>
			new Response(evil, { status: 200 })) as unknown as typeof fetch;
		await expect(ensureModel({ dir, fetchImpl })).rejects.toThrow(
			ModelVerificationError,
		);
		expect(fs.readdirSync(dir)).toEqual([]);
		expect(() => getModel(dir)).toThrow(ModelNotInstalled);
	});

	it("does not retry a 4xx", async () => {
		let calls = 0;
		const fetchImpl = (async () => {
			calls++;
			return new Response("gone", { status: 404 });
		}) as unknown as typeof fetch;
		await expect(ensureModel({ dir: tmpDir(), fetchImpl })).rejects.toThrow(
			/HTTP 404/,
		);
		expect(calls).toBe(1);
	});

	it("extracts only the pinned members, and stamps last", () => {
		const zip = new AdmZip();
		zip.addFile("a.zst", Buffer.from("A"));
		zip.addFile("b.zst", Buffer.from("B"));
		zip.addFile("../escape.txt", Buffer.from("x"));
		zip.addFile("extra.txt", Buffer.from("x"));
		const buf = zip.toBuffer();
		const pin = pinFor(buf, ["a.zst", "b.zst"]);
		const parent = tmpDir();
		const dir = path.join(parent, "model");
		installArchive(buf, dir, pin);
		expect(fs.readdirSync(dir).sort()).toEqual([
			".pinned-model",
			"a.zst",
			"b.zst",
		]);
		expect(fs.existsSync(path.join(parent, "escape.txt"))).toBe(false);
		expect(isModelInstalled(dir, pin)).toBe(true);
		expect(isModelInstalled(dir)).toBe(false); // stamp is the other pin's
	});

	it("fails on an archive missing a pinned member, without a stamp", () => {
		const zip = new AdmZip();
		zip.addFile("a.zst", Buffer.from("A"));
		const buf = zip.toBuffer();
		const dir = tmpDir();
		expect(() =>
			installArchive(buf, dir, pinFor(buf, ["a.zst", "b.zst"])),
		).toThrow(/missing b\.zst/);
		expect(fs.existsSync(path.join(dir, ".pinned-model"))).toBe(false);
	});

	// Several processes installing into an empty cache at once: one's install
	// deleted the values.dat another had just decompressed and was reading.
	it("a same-model reinstall keeps values.dat; a different model drops it", () => {
		const archive = (tag: string) => {
			const zip = new AdmZip();
			zip.addFile("a.zst", Buffer.from(tag));
			return zip.toBuffer();
		};
		const dir = tmpDir();
		const dat = path.join(dir, "values.dat");
		const first = archive("one");
		installArchive(first, dir, pinFor(first, ["a.zst"]));
		fs.writeFileSync(dat, "decompressed");
		installArchive(first, dir, pinFor(first, ["a.zst"]));
		expect(fs.existsSync(dat)).toBe(true);
		const second = archive("two");
		installArchive(second, dir, pinFor(second, ["a.zst"]));
		expect(fs.existsSync(dat)).toBe(false);
	});

	it("the install lock admits one holder at a time, and releases", async () => {
		const dir = tmpDir();
		const events: string[] = [];
		const holder = (name: string, ms: number) =>
			withInstallLock(dir, async () => {
				events.push(`${name}+`);
				await new Promise((r) => setTimeout(r, ms));
				events.push(`${name}-`);
				return name;
			});
		// mkdir is the lock, so this is the same exclusion another process gets.
		const results = await Promise.all([holder("a", 300), holder("b", 10)]);
		expect(results).toEqual(["a", "b"]);
		expect(events).toEqual(["a+", "a-", "b+", "b-"]);
		expect(fs.existsSync(path.join(dir, LOCK_DIR))).toBe(false);
		// ...and a holder that throws still releases it.
		await expect(
			withInstallLock(dir, async () => {
				throw new Error("boom");
			}),
		).rejects.toThrow("boom");
		expect(fs.existsSync(path.join(dir, LOCK_DIR))).toBe(false);
	});

	it("reclaims a lock left by a process that died holding it", async () => {
		const dir = tmpDir();
		const lock = path.join(dir, LOCK_DIR);
		fs.mkdirSync(lock);
		const old = (Date.now() - STALE_LOCK_MS - 60_000) / 1000;
		fs.utimesSync(lock, old, old);
		await expect(withInstallLock(dir, async () => "ok")).resolves.toBe("ok");
	});

	it("honours CAMOUFOX_FPGEN_DATA", () => {
		const old = process.env.CAMOUFOX_FPGEN_DATA;
		try {
			const dir = tmpDir();
			process.env.CAMOUFOX_FPGEN_DATA = dir;
			expect(modelDir()).toBe(dir);
			// Nothing there: the synchronous API says so instead of fetching.
			expect(() => new Generator().generate()).toThrow(ModelNotInstalled);
			expect(() => query("os")).toThrow(ModelNotInstalled);
		} finally {
			if (old === undefined) delete process.env.CAMOUFOX_FPGEN_DATA;
			else process.env.CAMOUFOX_FPGEN_DATA = old;
		}
		expect(modelDir()).not.toBe("");
	});
});

describe.skipIf(!MODEL.ok)("fpgen model on disk", () => {
	it("is installed and pinned", () => {
		expect(isModelInstalled()).toBe(true);
		expect(
			fs.readFileSync(path.join(modelDir(), ".pinned-model"), "utf-8").trim(),
		).toBe(MODEL_PIN.sha256);
	});

	it("decompresses values.dat on first synchronous load", () => {
		const src = modelDir();
		const dir = tmpDir();
		for (const f of [...MODEL_PIN.files, ".pinned-model"]) {
			fs.copyFileSync(path.join(src, f), path.join(dir, f));
		}
		expect(fs.existsSync(path.join(dir, "values.dat"))).toBe(false);
		const fresh = getModel(dir);
		const cached = getModel();
		const ids = cached.network.nodesInSamplingOrder[7].possibleValues;
		expect(fresh.lookupValueList(ids)).toEqual(cached.lookupValueList(ids));
		expect(fs.statSync(path.join(dir, "values.dat")).size).toBe(
			fs.statSync(path.join(src, "values.dat")).size,
		);
	}, 60_000);
});

describe.skipIf(!MODEL.ok)("fpgen behaviours kept from Python", () => {
	it("hands predicates the CASEFOLDED value, as Python does", () => {
		// So a predicate written against "Linux" matches nothing -- in Python
		// too (this is why camoufox's multi-OS lambda must compare lowercase).
		expect(() =>
			new Generator().generate({ os: (v: string) => v === "Linux" }),
		).toThrow(InvalidConstraints);
		const seen: unknown[] = [];
		new Generator().generate(
			{
				os: (v: string) => {
					seen.push(v);
					return v === "linux";
				},
			},
			{ target: "os" },
		);
		expect(seen.sort()).toEqual(["chromeos", "linux", "macos", "windows"]);
	});

	it("names errors like Python, so callers can tell them apart", () => {
		try {
			new Generator().generate({ os: "Plan9" });
		} catch (e) {
			expect((e as Error).name).toBe("InvalidConstraints");
			return;
		}
		throw new Error("expected InvalidConstraints");
	});

	it("relaxes the first condition when strict is off", () => {
		const chromeUa = (query("navigator.userAgent") as string[]).find(
			(u) => u.includes("Chrome/") && !u.includes("Firefox"),
		) as string;
		const g = new Generator();
		expect(() =>
			g.generate({ browser: "Firefox", "navigator.userAgent": chromeUa }),
		).toThrow(/is impossible with constraint/);
		const fp = g.generate(
			{ browser: "Firefox", "navigator.userAgent": chromeUa },
			{ strict: false },
		);
		expect(fp.navigator.userAgent).toBe(chromeUa);
		expect(fp.browser).not.toBe("Firefox");
	});

	it("takes a Set as alternatives and an array as one value", () => {
		const g = new Generator();
		for (let i = 0; i < 20; i++) {
			expect(["Linux", "Windows"]).toContain(
				g.generate({ os: new Set(["Linux", "Windows"]) }, { target: "os" }),
			);
		}
		expect(() => g.generate({ os: ["Linux", "Windows"] })).toThrow(
			InvalidConstraints,
		);
	});

	it("ignores undefined conditions", () => {
		expect(
			new Generator().generate(
				{ browser: "Firefox", os: undefined },
				{ target: "navigator.appName" },
			),
		).toBe("Netscape");
	});
});

describe("fpgen Python-semantics helpers", () => {
	it("parseOrdered keeps document order, integer-like keys included", () => {
		const m = parseOrdered('{"b":1,"10":2,"a":{"2":3,"1":4},"0":5}') as Map<
			string,
			any
		>;
		expect([...m.keys()]).toEqual(["b", "10", "a", "0"]);
		expect([...m.get("a").keys()]).toEqual(["2", "1"]);
		expect(parseOrdered('{"k:\\"x\\":":"v:1"}')).toEqual(
			new Map([['k:"x":', "v:1"]]),
		);
	});

	it("parsePyTyped keeps floats apart from ints", () => {
		const v = parsePyTyped('{"a":1.0,"b":1,"c":[2.5e3,"1.0"]}') as any;
		expect(v.a).toBeInstanceOf(PyFloat);
		expect(v.b).toBe(1);
		expect(v.c[0]).toEqual(new PyFloat(2500));
		expect(v.c[1]).toBe("1.0");
	});

	it("pyEquals follows Python ==", () => {
		expect(pyEquals(1, new PyFloat(1))).toBe(true);
		expect(pyEquals(true, 1)).toBe(true);
		expect(pyEquals({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 })).toBe(true);
		expect(pyEquals([1, 2], [2, 1])).toBe(false);
		expect(pyEquals("1", 1)).toBe(false);
		expect(pyEquals(null, 0)).toBe(false);
	});

	it("casefold matches str.casefold on the cases that differ from lower()", () => {
		expect(casefold("MacOS")).toBe("macos");
		expect(casefold("Straße")).toBe("strasse");
		expect(casefold("ΣΊΣΥΦΟς")).toBe("σίσυφοσ");
	});
});
