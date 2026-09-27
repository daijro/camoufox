#!/usr/bin/env node
/**
 * Fail if `dist/` is missing or older than `src/`.
 *
 * `src/captcha.ts` was added and then sat uncompiled: `dist/captcha.js` did not
 * exist at all, so `import { solveCaptcha } from "camoufox"` resolved to a build
 * that had never heard of it. Nothing complained — `dist/` is gitignored, the
 * package still imported, and only the missing export gave it away at runtime,
 * as `CaptchaSolverUnavailable`, which reads like a missing optional dependency
 * rather than a stale build.
 *
 * `prepare` now rebuilds on install, which covers the common path. This is the
 * guard for the rest: run it in CI or a pre-commit hook and a stale build is a
 * red check instead of a confusing runtime error.
 */
import { readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const src = join(root, "src");
const dist = join(root, "dist");

if (!existsSync(dist)) {
  console.error("dist/ does not exist — run `pnpm build`.");
  process.exit(1);
}

/** Every file under `dir`, recursively. */
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const newestDist = Math.max(...walk(dist).map((f) => statSync(f).mtimeMs));

// Sources newer than the newest build output. Anything here is not in dist.
const stale = walk(src)
  .filter((f) => statSync(f).mtimeMs > newestDist)
  .map((f) => relative(root, f));

// A .ts source with no corresponding .js in dist was never compiled at all —
// the captcha.ts case, and the one that actually bit.
const missing = walk(src)
  .filter((f) => f.endsWith(".ts") && !f.endsWith(".d.ts"))
  .filter((f) => !existsSync(join(dist, relative(src, f).replace(/\.ts$/, ".js"))))
  .map((f) => relative(root, f));

if (missing.length || stale.length) {
  if (missing.length) {
    console.error("Never compiled into dist/:");
    for (const f of missing) console.error(`  ${f}`);
  }
  if (stale.length) {
    console.error("Newer than dist/:");
    for (const f of stale) console.error(`  ${f}`);
  }
  console.error("\nRun `pnpm build`.");
  process.exit(1);
}

console.log("dist/ is up to date with src/");
