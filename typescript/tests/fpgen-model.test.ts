/**
 * Both launchers must load the same fpgen model: the Python one installs the
 * release in python/src/camoufox/fpgen-model.json, this one the release the
 * `fpgen` package pins. Bump them together.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { MODEL_PIN } from "fpgen-js";
import { describe, expect, it } from "vitest";

const PYTHON_PIN = path.resolve(
	import.meta.dirname,
	"../../python/src/camoufox/fpgen-model.json",
);

describe("fpgen model pin", () => {
	it("matches python/src/camoufox/fpgen-model.json", () => {
		const { note: _note, ...fields } = JSON.parse(
			fs.readFileSync(PYTHON_PIN, "utf-8"),
		);
		expect({ ...MODEL_PIN, files: [...MODEL_PIN.files] }).toEqual(fields);
	});
});
