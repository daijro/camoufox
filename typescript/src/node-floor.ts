/**
 * The Node.js floor (package.json `engines.node`), checked when the package
 * loads. fpgen-js reads its model archive with node:zlib's zstd;
 * Node.js added zstd in 22.15. Below that the first
 * fingerprint draw died with "zlib.zstdDecompressSync is not a function" from
 * inside fpgen-js; npm only warns on `engines`, so the package says it here.
 */
import * as zlib from "node:zlib";

export const NODE_FLOOR = "22.15";

/** Throws, naming the floor and this runtime, when node:zlib has no zstd. */
export function assertNodeFloor(
	z: { zstdDecompressSync?: unknown } = zlib,
	version: string = process.versions.node,
): void {
	if (typeof z.zstdDecompressSync !== "function") {
		throw new Error(
			`camoufox needs Node.js >= ${NODE_FLOOR} (node:zlib zstd, which the ` +
				`fpgen model archive needs); this is Node.js ${version}.`,
		);
	}
}

assertNodeFloor();
