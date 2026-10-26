/**
 * Mirrors python/tests/test_addons.py: the default addons are the ones the
 * browser bundles, under addons/<name>/ beside its binary.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, expect, it } from "vitest";
import { addDefaultAddons, getAddonPath } from "../src/addons.js";
import { recordWarnings } from "../src/warnings.js";

let tmp: string;

beforeEach(() => {
	tmp = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-addons-"));
});

afterEach(() => {
	fs.rmSync(tmp, { recursive: true, force: true });
});

/** A build's executable, with uBO bundled where packaging puts it. */
function build({ mac = false, bundled = true } = {}): string {
	const contents = path.join(tmp, "Camoufox.app", "Contents");
	const binary = mac
		? path.join(contents, "MacOS", "camoufox")
		: path.join(tmp, "camoufox-bin");
	const files = mac ? path.join(contents, "Resources") : tmp;
	fs.mkdirSync(path.dirname(binary), { recursive: true });
	fs.writeFileSync(binary, "");
	if (bundled) {
		fs.mkdirSync(path.join(files, "addons", "UBO"), { recursive: true });
		fs.writeFileSync(path.join(files, "addons", "UBO", "manifest.json"), "{}");
	}
	return binary;
}

it("loads the bundled addon beside the binary", async () => {
	const binary = build();
	const out: string[] = [];
	const { warnings } = await recordWarnings(() =>
		addDefaultAddons(out, undefined, binary),
	);
	expect(out).toEqual([path.join(tmp, "addons", "UBO")]);
	expect(warnings).toEqual([]);
});

it("finds it in Contents/Resources of a macOS app bundle", () => {
	const binary = build({ mac: true });
	const expected = path.join(
		tmp,
		"Camoufox.app",
		"Contents",
		"Resources",
		"addons",
		"UBO",
	);
	expect(getAddonPath("UBO", binary)).toBe(expected);
	const out: string[] = [];
	addDefaultAddons(out, undefined, binary);
	expect(out).toEqual([expected]);
});

it("leaves an excluded addon out without a warning", async () => {
	const binary = build({ bundled: false });
	const out: string[] = [];
	const { warnings } = await recordWarnings(() =>
		addDefaultAddons(out, ["UBO"], binary),
	);
	expect(out).toEqual([]);
	expect(warnings).toEqual([]);
});

it("launches a build without the addon without it, and says so", async () => {
	const binary = build({ bundled: false });
	const out: string[] = [];
	const { warnings } = await recordWarnings(() =>
		addDefaultAddons(out, undefined, binary),
	);
	expect(out).toEqual([]);
	expect(warnings).toHaveLength(1);
	expect(warnings[0].message).toContain(path.join(tmp, "addons", "UBO"));
	expect(warnings[0].message).toContain("exclude_addons");
});

it("does not count a partial directory", async () => {
	const binary = build({ bundled: false });
	fs.mkdirSync(path.join(tmp, "addons", "UBO"), { recursive: true });
	const out: string[] = [];
	await recordWarnings(() => addDefaultAddons(out, undefined, binary));
	expect(out).toEqual([]);
});
