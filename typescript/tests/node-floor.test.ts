/** The package states its Node.js floor instead of crashing inside fpgen-js. */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { assertNodeFloor, NODE_FLOOR } from "../src/node-floor.js";

const PACKAGE = JSON.parse(
	fs.readFileSync(
		path.join(
			path.dirname(fileURLToPath(import.meta.url)),
			"..",
			"package.json",
		),
		"utf-8",
	),
);

describe("Node.js floor", () => {
	it("is the one package.json declares", () => {
		expect(PACKAGE.engines.node.replace(/[>=\s]/g, "")).toBe(NODE_FLOOR);
	});

	it("names the floor and the runtime when node:zlib has no zstd", () => {
		expect(() => assertNodeFloor({}, "20.20.2")).toThrow(
			`camoufox needs Node.js >= ${NODE_FLOOR} (node:zlib zstd, which the fpgen model archive needs); this is Node.js 20.20.2.`,
		);
	});

	it("passes on this runtime", () => {
		expect(() => assertNodeFloor()).not.toThrow();
	});
});
