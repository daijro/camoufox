/**
 * Mirrors pythonlib/tests/test_download_integrity.py: a release asset whose
 * bytes do not match the GitHub-published sha256 digest must abort the
 * install before extraction.
 */
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { CorruptedDownload } from "../src/exceptions.js";
import { verifySha256 } from "../src/pkgman.js";

// Large enough to span several read() blocks, so a single-shot read
// regression cannot pass by accident.
const PAYLOAD = Buffer.from("camoufox release asset".repeat(100_000));
const DIGEST = createHash("sha256").update(PAYLOAD).digest("hex");

describe("verifySha256", () => {
	it("accepts a matching digest", () => {
		expect(() => verifySha256(PAYLOAD, DIGEST, "asset")).not.toThrow();
	});

	it("compares digests case-insensitively", () => {
		expect(() =>
			verifySha256(PAYLOAD, DIGEST.toUpperCase(), "asset"),
		).not.toThrow();
	});

	const mutations: Record<string, (b: Buffer) => Buffer> = {
		"first-byte-flipped": (b) =>
			Buffer.concat([Buffer.from([b[0] ^ 0xff]), b.subarray(1)]),
		"last-bit-flipped": (b) =>
			Buffer.concat([b.subarray(0, -1), Buffer.from([b[b.length - 1] ^ 1])]),
		truncated: (b) => b.subarray(0, -1),
		appended: (b) => Buffer.concat([b, Buffer.from([0])]),
		empty: () => Buffer.alloc(0),
	};
	for (const [name, mutate] of Object.entries(mutations)) {
		it(`aborts the install on a tampered payload (${name})`, () => {
			expect(() => verifySha256(mutate(PAYLOAD), DIGEST, "asset")).toThrow(
				CorruptedDownload,
			);
		});
	}

	it("names both digests in the error", () => {
		let message = "";
		try {
			verifySha256(Buffer.from("wrong"), DIGEST, "Camoufox v1.2.3");
		} catch (e) {
			expect(e).toBeInstanceOf(CorruptedDownload);
			message = (e as Error).message;
		}
		expect(message).toContain("Camoufox v1.2.3");
		expect(message).toContain(DIGEST);
		expect(message).toContain(
			createHash("sha256").update("wrong").digest("hex"),
		);
	});

	for (const absent of [null, undefined, ""]) {
		it(`does not block the install without a digest (${JSON.stringify(absent)})`, () => {
			expect(() => verifySha256(PAYLOAD, absent, "asset")).not.toThrow();
		});
	}

	it("verifies a real temporary file, as the install path does", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-sha-"));
		try {
			const file = path.join(dir, "asset.zip");
			fs.writeFileSync(file, PAYLOAD);
			expect(() => verifySha256(file, DIGEST, "asset")).not.toThrow();
			fs.appendFileSync(file, "x");
			expect(() => verifySha256(file, DIGEST, "asset")).toThrow(
				CorruptedDownload,
			);
			// The file is untouched for the extraction that follows.
			expect(fs.readFileSync(file).subarray(0, PAYLOAD.length)).toEqual(
				PAYLOAD,
			);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});
