// Ship every non-TS file the package needs at runtime into dist/:
//   DATA_FILES (src/paths.ts) from pythonlib/camoufox/ -> dist/data-files/
//     (presets, fonts, voices, territoryInfo.xml, repos.yml, warnings.yml, ...)
//   src/fpgen/NOTICE -> dist/fpgen/NOTICE (Apache-2.0 attribution for the port)
// Runs after tsc, so the list comes from the compiled paths.js.
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PYTHONLIB = path.resolve(ROOT, "..", "pythonlib", "camoufox");
const DATA = path.join(ROOT, "dist", "data-files");

fs.rmSync(DATA, { recursive: true, force: true });
const { DATA_FILES } = await import(path.join(ROOT, "dist", "paths.js"));
fs.mkdirSync(DATA, { recursive: true });
for (const name of DATA_FILES) {
	fs.copyFileSync(path.join(PYTHONLIB, name), path.join(DATA, name));
}
console.log(`copied ${DATA_FILES.length} data files from pythonlib -> dist/data-files`);

const notice = path.join(ROOT, "dist", "fpgen", "NOTICE");
fs.mkdirSync(path.dirname(notice), { recursive: true });
fs.copyFileSync(path.join(ROOT, "src", "fpgen", "NOTICE"), notice);
console.log("copied src/fpgen/NOTICE -> dist/fpgen/NOTICE");
