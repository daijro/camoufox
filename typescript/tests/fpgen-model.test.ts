/**
 * Both launchers must load the same fpgen model: the Python one installs the
 * release in browser/scripts/data/fpgen-model.json, this one the release the
 * `fpgen` package pins. Bump them together.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { MODEL_PIN } from "fpgen";
import { describe, expect, it } from "vitest";

const REPO_PIN = path.resolve(
	import.meta.dirname,
	"../../browser/scripts/data/fpgen-model.json",
);

describe("fpgen model pin", () => {
	it("matches browser/scripts/data/fpgen-model.json", () => {
		const { note: _note, ...fields } = JSON.parse(
			fs.readFileSync(REPO_PIN, "utf-8"),
		);
		expect({ ...MODEL_PIN, files: [...MODEL_PIN.files] }).toEqual(fields);
	});
});
