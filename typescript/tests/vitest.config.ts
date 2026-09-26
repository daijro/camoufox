import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The config lives in the test dir, so pin the root to the package dir rather
// than letting it fall out of the caller's cwd.
const PACKAGE_ROOT = path.resolve(
	path.dirname(fileURLToPath(import.meta.url)),
	"..",
);

export default defineConfig({
	root: PACKAGE_ROOT,
	test: {
		include: ["tests/**/*.test.ts"],
		globalSetup: ["tests/golden-setup.ts"],
		testTimeout: 30_000,
		hookTimeout: 30_000,
	},
});
