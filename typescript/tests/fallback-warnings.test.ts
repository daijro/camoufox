/**
 * Port of pythonlib/tests/test_fallback_warnings.py (identity half; the launch
 * half is in launch.test.ts): every place an identity falls back to a
 * substitute value says so, with a report block to paste into an issue.
 *
 * Python breaks the draws with monkeypatch; here they read a copy of the data
 * files with one file removed or corrupted, which fails the same way.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DATA_FILES, LOCAL_DATA } from "../src/paths.js";
import { prerequisite } from "./prereq.js";

const REPORT =
	"Please report this at https://github.com/daijro/camoufox/issues/new";

let modelReady = true;
try {
	await (await import("../src/fpgen/index.js")).ensureModel();
} catch (e) {
	modelReady = prerequisite("fpgen-model", false, String(e));
}

let tmp: string;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-fallback-"));
	vi.resetModules();
});

afterEach(() => {
	vi.doUnmock("../src/paths.js");
	fs.rmSync(tmp, { recursive: true, force: true });
});

const missing = (file: string) => (dir: string) =>
	fs.rmSync(path.join(dir, file));
const corrupt = (file: string) => (dir: string) =>
	fs.writeFileSync(path.join(dir, file), "{not json");

/** fingerprints.ts and warnings.ts reading a data directory `broken` has altered. */
async function withData(broken: (dir: string) => void) {
	const data = path.join(tmp, "data-files");
	fs.mkdirSync(data, { recursive: true });
	for (const name of DATA_FILES)
		fs.copyFileSync(path.join(LOCAL_DATA, name), path.join(data, name));
	broken(data);
	vi.doMock("../src/paths.js", async (importOriginal) => ({
		...(await importOriginal<typeof import("../src/paths.js")>()),
		LOCAL_DATA: data,
	}));
	await (await import("../src/fpgen/index.js")).ensureModel();
	return {
		fp: await import("../src/fingerprints.js"),
		warnings: await import("../src/warnings.js"),
	};
}

/** The one FallbackWarning `fn` emitted, checked for its report block. */
async function report(
	warnings: typeof import("../src/warnings.js"),
	fn: () => unknown,
): Promise<{ result: any; text: string }> {
	const { result, error, warnings: caught } = await warnings.recordWarnings(fn);
	if (error) throw error;
	const fallbacks = caught.filter((w) => w.category === "FallbackWarning");
	expect(fallbacks).toHaveLength(1);
	const text = fallbacks[0].message;
	for (const part of [REPORT, "camoufox:", "node:", "os:", "error:"]) {
		expect(text).toContain(part);
	}
	return { result, text };
}

function preset(fp: typeof import("../src/fingerprints.js")) {
	const first = fp.loadPresets("152")?.presets.windows[0];
	return { ...first, fonts: ["Arial"] };
}

it("a failed preset font draw falls back to the preset's fonts", async () => {
	const { fp, warnings } = await withData(missing("fonts.json"));
	const { result: config, text } = await report(warnings, () =>
		fp.fromPreset(preset(fp), "152"),
	);
	expect(text).toContain("ENOENT");
	expect(text).toContain("the preset's recorded fonts");
	expect(config.fonts).toContain("Arial");
});

it("a failed preset voice draw warns", async () => {
	const { fp, warnings } = await withData(corrupt("voice-manifests.json"));
	const { text } = await report(warnings, () =>
		fp.fromPreset(preset(fp), "152"),
	);
	expect(text).toContain("error: SyntaxError:");
});

describe.skipIf(!modelReady)("context draws", () => {
	it.each([
		["fonts.json", missing("fonts.json"), "fonts", "ENOENT"],
		[
			"voice-manifests.json",
			corrupt("voice-manifests.json"),
			"voices",
			"SyntaxError",
		],
	])("an unreadable %s leaves the launch-time value", async (_file, broken, key, error) => {
		const { fp, warnings } = await withData(broken);
		const { result: context, text } = await report(warnings, () =>
			fp.generateContextFingerprint({ os: "linux" }),
		);
		expect(text).toContain(error);
		expect(key in context.config).toBe(false);
	});
});

it.each([
	"font-groups.json",
	"font-bases.json",
])("an unreadable %s warns and is read as empty", async (file) => {
	const { fp, warnings } = await withData(missing(file));
	const { result: fonts, text } = await report(warnings, () =>
		fp.generateRandomFontSubset("windows", 1),
	);
	expect(text).toContain(`Reading ${file}`);
	expect(fonts.length).toBeGreaterThan(0);
});

it("an error the data cannot raise is not swallowed", async () => {
	const { fp } = await withData((dir) =>
		fs.writeFileSync(path.join(dir, "fonts.json"), "null"),
	);
	expect(() => fp.fromPreset(preset(fp), "152")).toThrow(TypeError);
});
