// Launch the INSTALLED camoufox npm package, run the shared page probe, then
// click and type as python_probe.py's "interact" mode does: its Node twin, used
// by ci/run_install.py.
//
//   echo '{"url": "...", "probe": "<path to probe.js>", "text": "...", "kwargs": {...}}' | node node_probe.mjs
//
// A bare `camoufox` import resolves from this file's directory, so the caller
// copies it into the project that installed the packed tarball. Prints one
// JSON object, {"probe", "events", "value"}, as the last line of stdout.
import fs from "node:fs";
import { Camoufox } from "camoufox";

const req = JSON.parse(fs.readFileSync(0, "utf-8"));
const probe = fs.readFileSync(req.probe, "utf-8");
const browser = await Camoufox(req.kwargs);
try {
	const page = await browser.newPage();
	await page.goto(req.url);
	// evaluate() runs a string as an expression, so call the probe explicitly.
	const out = await page.evaluate(`(${probe})()`);
	await page.locator("#button").click();
	await page.locator("#input").pressSequentially(req.text);
	const log = await page.locator("#events").textContent();
	const events = log
		.split("\n")
		.filter(Boolean)
		.map((line) => JSON.parse(line));
	const value = await page.locator("#input").inputValue();
	process.stdout.write(`\n${JSON.stringify({ probe: out, events, value })}\n`);
} finally {
	await browser.close();
}
