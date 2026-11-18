/**
 * custom() humanize engines: the factory, the seeded streams (parity with the
 * Python launcher's), the page wrappers and play()'s pacing. The twin of
 * python/tests/test_humanize_custom.py, against the same fake page and the same
 * recorded sequence, browser/tests/humanize/custom-sequence.json.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { errors } from "playwright-core";
import { afterEach, describe, expect, it, vi } from "vitest";
import { attach, validateSteps } from "../src/_humanize_custom.js";
import {
	CHANNELS,
	type CustomEngine,
	channelStream,
	custom,
	drivenChannels,
	myuri,
	normalize,
	raw,
	SeededRng,
	splitmix64,
} from "../src/humanize.js";
import { launchServer } from "../src/server.js";
import { NewBrowser } from "../src/sync_api.js";
import * as warnings from "../src/warnings.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BROWSER = path.resolve(HERE, "..", "..", "browser");
const json = (...parts: string[]) =>
	JSON.parse(fs.readFileSync(path.join(BROWSER, ...parts), "utf-8"));
const VECTORS = json("tests", "humanize", "rng-vectors.json");
const SEQUENCE = json("tests", "humanize", "custom-sequence.json");

const noop: CustomEngine = () => undefined;

describe("streams", () => {
	it("gives the reference outputs", () => {
		expect(splitmix64(0n)).toBe(0xe220a8397b1dcdafn);
		expect(splitmix64(0x9e3779b97f4a7c15n)).toBe(0x6e789e6aa1b965f4n);
		const rng = SeededRng(0);
		expect([rng(), rng(), rng()].map((d) => Math.round(d * 2 ** 32))).toEqual([
			1144304738, 1416247, 958946056,
		]);
	});

	it("matches the pinned vectors draw for draw", () => {
		for (const [seed, value] of VECTORS.splitmix64)
			expect(splitmix64(BigInt(seed))).toBe(BigInt(value));
		for (const entry of VECTORS.streams)
			for (const channel of CHANNELS) {
				const stream = channelStream(BigInt(entry.seed), channel);
				const draws = entry[channel].map(() => stream() * 2 ** 32);
				expect(draws).toEqual(entry[channel]);
				expect(stream.position).toBe(entry[channel].length);
			}
	});

	it("has the helpers", () => {
		const first = channelStream(7, "mouse")();
		expect(channelStream(7, "mouse").uniform(10, 20)).toBe(10 + 10 * first);
		expect(channelStream(7, "mouse").random()).toBe(first);
		expect(() => channelStream(1, "touch")).toThrow("unknown humanize channel");
	});
});

describe("factory and config", () => {
	it("custom() takes a function", () => {
		expect(() => custom(42 as any)).toThrow("custom() takes the function");
		expect(() => normalize({ mouse: "custom" })).toThrow(
			"needs its function, as custom(fn)",
		);
		expect(() =>
			normalize({ mouse: { ...custom(noop), options: { speed: 1 } } }),
		).toThrow("custom() takes no options");
		expect(
			drivenChannels({ mouse: custom(noop), keyboard: raw(), scroll: raw() }),
		).toEqual(["mouse"]);
		expect(drivenChannels({ mouse: raw() })).toEqual(["keyboard", "scroll"]);
		expect(drivenChannels(null)).toEqual([]);
	});

	it("a channel set to null is refused; an omitted one is myuri", () => {
		expect(() => normalize({ mouse: null })).toThrow(
			'humanize["mouse"] must be myuri(), custom(fn) or raw()',
		);
		expect(normalize({}).engines.mouse.engine).toBe("myuri");
		expect(normalize({ seed: null }).seed).toBeUndefined();
	});

	it("NewBrowser attaches the engines to what it launched", async () => {
		const browser = fakeBrowser();
		const launch = vi.fn(async () => browser);
		const calls: number[][] = [];
		const launched: any = await NewBrowser({ launch } as any, {
			from_options: { headless: true },
			humanize: {
				mouse: custom((_p, x, y) => {
					calls.push([x, y]);
				}),
				keyboard: raw(),
				scroll: raw(),
			},
		});
		await (await launched.newPage()).mouse.move(1, 2);
		expect(calls).toEqual([[1, 2]]);
	});

	it("NewBrowser checks the engines before it launches", async () => {
		const launch = vi.fn();
		await expect(
			NewBrowser({ launch } as any, {
				from_options: { headless: true },
				humanize: { mouse: "custom" },
			}),
		).rejects.toThrow("needs its function");
		expect(launch).not.toHaveBeenCalled();
	});

	it("launchServer refuses custom()", async () => {
		await expect(
			launchServer({ humanize: { mouse: custom(noop) } }),
		).rejects.toThrow("launch_server() cannot run humanize engines");
	});
});

describe("play() validation", () => {
	it.each<[unknown, string]>([
		["move", "takes a list of steps"],
		[[["hop", 1, 2, 0]], "the kind must be"],
		[[["move", 1, 2]], "move takes 3 values"],
		[[["move", 1, 2, -1]], "t must be a finite number"],
		[
			[
				["move", 1, 2, 5],
				["move", 1, 2, 4],
			],
			"goes back in time",
		],
		[[["move", Number.NaN, 2, 0]], "finite numbers"],
		[[["move", Number.POSITIVE_INFINITY, 2, 0]], "finite numbers"],
		[[["down", "side", 0]], "the button must be"],
		[[["key", "a", "tap", 0]], 'key takes a key name and "down" or "up"'],
		[[["text", 5, 0]], "text takes a string"],
		[[["move", 1, 2, true]], "t must be"],
	])("rejects %j", (steps, message) => {
		expect(() => validateSteps(steps)).toThrow(message);
	});

	it("names the bad step", () => {
		expect(() =>
			validateSteps([
				["down", "left", 0],
				["up", "side", 3],
			]),
		).toThrow("play() step 1 [ 'up', 'side', 3 ]");
	});
});

// ---- the fake page ---------------------------------------------------------

type Box = { x: number; y: number; width: number; height: number };

/** A browser whose calls record what reaches Playwright. Each has its own
 * Locator and Frame classes, like Playwright's, so patching one stays here. */
function fakeBrowser(latency = 0) {
	const events: unknown[][] = [];
	const log = (...event: unknown[]) => {
		events.push(event);
	};
	const boxes: Record<string, [Box, boolean]> = {
		html: [{ x: 0, y: 0, width: 1000, height: 700 }, true],
		"#far": [{ x: 100, y: 900, width: 80, height: 30 }, false],
		"#name": [{ x: 40, y: 120, width: 200, height: 24 }, true],
		"#near": [{ x: 500, y: 300, width: 50, height: 20 }, true],
	};

	class FakeLocator {
		constructor(
			readonly owner: FakePage,
			readonly selector: string,
		) {}
		page() {
			return this.owner;
		}
		first() {
			return new FakeLocator(this.owner, this.selector);
		}
		async click(o?: any) {
			if (!o?.trial && !this.owner.checked.delete(this.selector))
				this.owner.checked.add(this.selector);
			log(
				"locator.click",
				this.selector,
				o?.position ?? null,
				o?.delay ?? null,
			);
		}
		async dblclick(o?: any) {
			log("locator.dblclick", this.selector, o?.position ?? null);
		}
		async hover(o?: any) {
			log("locator.hover", this.selector, o?.position ?? null);
		}
		async check(o?: any) {
			log("locator.check", this.selector, o?.position ?? null);
		}
		async uncheck(o?: any) {
			log("locator.uncheck", this.selector, o?.position ?? null);
		}
		async fill(value: string) {
			log("locator.fill", this.selector, value);
		}
		async type(text: string) {
			log("locator.type", this.selector, text);
		}
		async pressSequentially(text: string) {
			log("locator.pressSequentially", this.selector, text);
		}
		async press(key: string) {
			log("locator.press", this.selector, key);
		}
		async scrollIntoViewIfNeeded() {
			boxes[this.selector][1] = true;
			log("locator.scrollIntoViewIfNeeded", this.selector);
		}
		async selectText() {
			log("locator.selectText", this.selector);
		}
		async focus() {
			log("locator.focus", this.selector);
		}
		async isChecked() {
			return this.owner.checked.has(this.selector);
		}
		async boundingBox() {
			return { ...boxes[this.selector][0] };
		}
		async evaluate(script: unknown) {
			const source = String(script);
			if (source.includes("borderLeftWidth")) return [2, 3];
			if (source.includes("elementFromPoint")) {
				// What covers the point at each press, until the list runs out.
				this.owner.aimed = this.selector;
				return this.owner.covered.shift() ?? null;
			}
			return boxes[this.selector][1];
		}
	}

	class FakeFrame {
		constructor(readonly owner: FakePage) {}
		page() {
			return this.owner;
		}
		locator(selector: string) {
			return this.owner.locator(selector);
		}
		async click(selector: string) {
			log("page.frame.click", selector);
		}
		async dblclick(selector: string) {
			log("page.frame.dblclick", selector);
		}
		async hover(selector: string) {
			log("page.frame.hover", selector);
		}
		async check(selector: string) {
			log("page.frame.check", selector);
		}
		async uncheck(selector: string) {
			log("page.frame.uncheck", selector);
		}
		async fill(selector: string, value: string) {
			log("page.frame.fill", selector, value);
		}
		async type(selector: string, text: string) {
			log("page.frame.type", selector, text);
		}
		async press(selector: string, key: string) {
			log("page.frame.press", selector, key);
		}
	}

	class FakePage {
		readonly frame = new FakeFrame(this);
		readonly checked = new Set<string>();
		// The checkbox the next release toggles: what the last hit test found.
		aimed: string | null = null;
		covered: string[] = [];
		timeout = 30000;
		// Playwright's client keeps the default timeout here.
		readonly _timeoutSettings = {
			timeout: () => ({ timeout: this.timeout }),
		};
		readonly mouse = {
			latency,
			move: async (x: number, y: number) => {
				log("mouse.move", x, y);
				if (this.mouse.latency)
					await new Promise((r) => setTimeout(r, this.mouse.latency));
			},
			down: async (o?: any) =>
				log("mouse.down", o?.button ?? "left", o?.clickCount ?? 1),
			up: async (o?: any) => {
				log("mouse.up", o?.button ?? "left", o?.clickCount ?? 1);
				if (this.aimed && !this.checked.delete(this.aimed))
					this.checked.add(this.aimed);
			},
			wheel: async (dx: number, dy: number) => log("mouse.wheel", dx, dy),
			click: async (x: number, y: number, o?: any) =>
				log("mouse.click", x, y, o?.delay ?? null),
			dblclick: async (x: number, y: number) => log("mouse.dblclick", x, y),
		};
		readonly keyboard = {
			down: async (key: string) => log("keyboard.down", key),
			up: async (key: string) => log("keyboard.up", key),
			insertText: async (text: string) => log("keyboard.insertText", text),
			type: async (text: string) => log("keyboard.type", text),
			press: async (key: string) => log("keyboard.press", key),
		};
		constructor(readonly owner: FakeContext) {}
		context() {
			return this.owner;
		}
		mainFrame() {
			return this.frame;
		}
		locator(selector: string) {
			return new FakeLocator(this, selector);
		}
		async evaluate() {
			return [1000, 700];
		}
		async click(selector: string) {
			log("page.click", selector);
		}
		async dblclick(selector: string) {
			log("page.dblclick", selector);
		}
		async hover(selector: string) {
			log("page.hover", selector);
		}
		async check(selector: string) {
			log("page.check", selector);
		}
		async uncheck(selector: string) {
			log("page.uncheck", selector);
		}
		async fill(selector: string, value: string) {
			log("page.fill", selector, value);
		}
		async type(selector: string, text: string) {
			log("page.type", selector, text);
		}
		async press(selector: string, key: string) {
			log("page.press", selector, key);
		}
	}

	class FakeContext {
		private readonly open: FakePage[] = [];
		private readonly handlers: ((page: FakePage) => void)[] = [];
		pages() {
			return this.open;
		}
		on(event: string, handler: (page: FakePage) => void) {
			expect(event).toBe("page");
			this.handlers.push(handler);
		}
		openPage() {
			const page = new FakePage(this);
			this.open.push(page);
			for (const handler of this.handlers) handler(page);
			return page;
		}
	}

	const made: FakeContext[] = [];
	return {
		events,
		boxes,
		contexts: () => made,
		async newContext() {
			const context = new FakeContext();
			made.push(context);
			return context;
		},
		async newPage() {
			const context = new FakeContext();
			made.push(context);
			return context.openPage();
		},
	} as any;
}

/** A page whose channels are raw() except those `humanize` names. */
async function attachedPage(humanize: Record<string, unknown>, latency = 0) {
	const browser = fakeBrowser(latency);
	attach(browser, { ...allRaw(), ...humanize }, "linux");
	return { browser, page: await browser.newPage() };
}

const allRaw = () => Object.fromEntries(CHANNELS.map((c) => [c, raw()]));

// ---- the reference engines -------------------------------------------------

/** Three engines that draw from their streams, play steps, and use original. */
function referenceEngines(log: unknown[][]) {
	const at = { x: 0, y: 0 };
	const path = (x: number, y: number, rng: SeededRng) => {
		const n = 3 + Math.floor(rng() * 4);
		const { x: sx, y: sy } = at;
		const steps = [];
		for (let i = 1; i <= n; i += 1) {
			const f = i / n;
			const jitter = (rng() - 0.5) * 4 * (1 - f);
			steps.push([
				"move",
				sx + (x - sx) * f + jitter,
				sy + (y - sy) * f - jitter,
				i * 2,
			]);
		}
		at.x = x;
		at.y = y;
		return steps;
	};
	const move: CustomEngine = async (
		_page,
		x,
		y,
		{ original, rng, play, click },
	) => {
		log.push(["fn.mouse", x, y, click ? click.clickCount : null]);
		await play(path(x, y, rng));
		if (click)
			return original(undefined, undefined, {
				delay: 90 + Math.floor(rng() * 30),
			});
	};
	const keys: CustomEngine = (_page, text, { original, rng, play, kind }) => {
		log.push(["fn.keyboard", kind, text]);
		if (kind === "press") return original();
		const steps = [];
		let t = 0;
		for (const ch of text) {
			steps.push(["key", ch, "down", t]);
			t += 1 + Math.floor(rng() * 3);
			steps.push(["key", ch, "up", t]);
		}
		return play(steps);
	};
	const scroll: CustomEngine = (_page, target, { original, rng, play }) => {
		if (Array.isArray(target)) {
			log.push(["fn.scroll", target]);
			const n = 2 + Math.floor(rng() * 3);
			return play(
				Array.from({ length: n }, (_, i) => [
					"wheel",
					target[0] / n,
					target[1] / n,
					i,
				]),
			);
		}
		log.push(["fn.scroll", target.selector]);
		return original();
	};
	return { move, keys, scroll };
}

/** Every wrapped method once, on a browser with all three channels custom. */
async function scenario() {
	const browser = fakeBrowser();
	const { move, keys, scroll } = referenceEngines(browser.events);
	attach(
		browser,
		{
			mouse: custom(move),
			keyboard: custom(keys),
			scroll: custom(scroll),
			seed: 1234,
		},
		"linux",
	);
	const page = await browser.newPage();
	await page.mouse.move(300, 200);
	await page.mouse.wheel(0, 480);
	await page.locator("#far").click();
	await page.locator("#near").hover({ position: { x: 5, y: 6 } });
	await page.locator("#name").fill("Hi there");
	await page.keyboard.press("Enter");
	await page.keyboard.type("ok");
	await page.mouse.click(10, 20);
	await page.click("#near");
	await page.fill("#name", "");
	await page.locator("#near").click({ trial: true });
	return browser.events as unknown[][];
}

describe("the scenario", () => {
	it("matches the sequence the Python launcher recorded", async () => {
		expect(SEQUENCE.seed).toBe(1234);
		expect(await scenario()).toEqual(SEQUENCE.events);
	});
});

// ---- wrappers --------------------------------------------------------------

describe("wrappers", () => {
	const recordingMouse = () => {
		const calls: [number, number][] = [];
		const fn: CustomEngine = (_page, x, y, { original }) => {
			calls.push([x, y]);
			return original();
		};
		return { calls, fn };
	};

	it("a click is pressed by the mouse engine, at its point", async () => {
		const seen: unknown[] = [];
		const { browser, page } = await attachedPage({
			mouse: custom((_p, x, y, { original, click }) => {
				seen.push([x, y, click]);
				return original(x + 1, y - 1, { delay: 104 });
			}),
		});
		await page.locator("#near").click();
		const box = browser.boxes["#near"][0];
		expect(seen).toEqual([[525, 310, { button: "left", clickCount: 1, box }]]);
		// The engine never moved, so the press moves to its point, then presses there.
		expect(browser.events).toEqual([
			["locator.scrollIntoViewIfNeeded", "#near"],
			["mouse.move", 526, 309],
			["mouse.down", "left", 1],
			["mouse.up", "left", 1],
		]);
	});

	it("a press after the engine moved sends no other move", async () => {
		const { browser, page } = await attachedPage({
			mouse: custom(async (p, x, y, { original }) => {
				await p.mouse.move(x, y);
				return original(x, y);
			}),
		});
		await page.locator("#near").dblclick();
		await page.mouse.click(10, 20);
		expect(browser.events).toEqual([
			["locator.scrollIntoViewIfNeeded", "#near"],
			["mouse.move", 525, 310],
			["mouse.down", "left", 1],
			["mouse.up", "left", 1],
			["mouse.down", "left", 2],
			["mouse.up", "left", 2],
			["mouse.move", 10, 20],
			["mouse.down", "left", 1],
			["mouse.up", "left", 1],
		]);
	});

	it("a covered point is reached for again", async () => {
		const { calls, fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		page.covered = ["<div> intercepts pointer events"];
		await page.locator("#near").click();
		expect(calls).toEqual([
			[525, 310],
			[525, 310],
		]);
		expect(
			browser.events.filter((e: unknown[]) => e[0] === "mouse.down").length,
		).toBe(1);
	});

	it("a forced press skips the check", async () => {
		const { calls, fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		page.covered = ["<div> intercepts pointer events"];
		await page.locator("#near").click({ force: true });
		expect(calls).toEqual([[525, 310]]);
		expect(
			browser.events.filter((e: unknown[]) => e[0] === "mouse.down").length,
		).toBe(1);
		expect(page.covered).toHaveLength(1);
	});

	it("a point covered past the timeout raises", async () => {
		const { fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		page.covered = Array(100).fill("<div> intercepts pointer events");
		const error = await page
			.locator("#near")
			.click({ timeout: 150 })
			.catch((e: Error) => e);
		expect(error).toBeInstanceOf(errors.TimeoutError);
		expect(error.message).toContain("<div> intercepts pointer events");
		expect(browser.events.map((e: unknown[]) => e[0])).not.toContain(
			"mouse.down",
		);
	});

	it("a zero timeout waits for the point", async () => {
		const { fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		page.covered = Array(3).fill("<div> intercepts pointer events");
		page.timeout = 0;
		await page.locator("#near").click();
		expect(
			browser.events.filter((e: unknown[]) => e[0] === "mouse.down").length,
		).toBe(1);
	});

	it("a hover is the engine move alone", async () => {
		const { fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		await page.locator("#near").hover();
		expect(browser.events).toEqual([
			["locator.scrollIntoViewIfNeeded", "#near"],
			["mouse.move", 525, 310],
		]);
	});

	it("myuri moves to a point in the box and clicks there", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri(), seed: 3 });
		await page.locator("#near").click();
		const box = browser.boxes["#near"][0];
		const moves = browser.events.filter((e) => e[0] === "mouse.move");
		expect(moves.length).toBeGreaterThan(1);
		expect(browser.events.map((e) => e[0])).not.toContain("locator.click");
		// The press is where the path ends, inside the box, with no move after it.
		const [, x, y] = moves[moves.length - 1] as [string, number, number];
		expect(x).toBeGreaterThanOrEqual(box.x);
		expect(x).toBeLessThanOrEqual(box.x + box.width);
		expect(y).toBeGreaterThanOrEqual(box.y);
		expect(y).toBeLessThanOrEqual(box.y + box.height);
		expect(browser.events.slice(-2)).toEqual([
			["mouse.down", "left", 1],
			["mouse.up", "left", 1],
		]);
	});

	it("myuri turns a wheel in mouse notches", async () => {
		const { browser, page } = await attachedPage({ scroll: myuri(), seed: 3 });
		await page.mouse.wheel(0, 300);
		const wheels = browser.events.filter((e) => e[0] === "mouse.wheel");
		// Windows and Linux mouse wheels send one 100 px event a notch
		// (docs/input-dispatch.md).
		expect(wheels.length).toBeGreaterThan(0);
		for (const [, dx, dy] of wheels as [string, number, number][]) {
			expect(dx).toBe(0);
			expect(Math.abs(dy)).toBe(100);
		}
	});

	it("a click the engine never presses does not happen", async () => {
		const { browser, page } = await attachedPage({ mouse: custom(noop) });
		await page.locator("#near").click();
		await page.mouse.click(10, 20);
		expect(browser.events).toEqual([
			["locator.scrollIntoViewIfNeeded", "#near"],
		]);
	});

	it("the click before a fill uses the mouse engine", async () => {
		const { calls, fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		await page.fill("#name", "text");
		expect(calls).toEqual([[140, 132]]);
		expect(browser.events.map((e: unknown[]) => e[0]).slice(-2)).toEqual([
			"mouse.up",
			"locator.fill",
		]);
	});

	it("a keyboard engine alone still clicks before a fill", async () => {
		const { browser, page } = await attachedPage({ keyboard: custom(noop) });
		await page.fill("#name", "text");
		const names = browser.events.map((e: unknown[]) => e[0]);
		expect(names.indexOf("locator.click")).toBeLessThan(
			names.indexOf("locator.selectText"),
		);
		expect(names).toContain("locator.click");
	});

	it("check and frame methods take the locator flow", async () => {
		const { calls, fn } = recordingMouse();
		const { page } = await attachedPage({ mouse: custom(fn) });
		await page.check("#near");
		await page.check("#near"); // already checked: no click
		await page.mainFrame().click("#near");
		expect(calls).toEqual([
			[525, 310],
			[525, 310],
		]);
	});

	it("an engine calling its own channel reaches Playwright", async () => {
		const { browser, page } = await attachedPage({
			mouse: custom(async (p, x, y) => {
				await p.mouse.move(x - 1, y - 1); // not back into this function
				await p.mouse.move(x, y);
			}),
		});
		await page.mouse.move(50, 60);
		expect(browser.events).toEqual([
			["mouse.move", 49, 59],
			["mouse.move", 50, 60],
		]);
	});

	it("exceptions propagate", async () => {
		const { page } = await attachedPage({
			keyboard: custom(() => {
				throw new Error("engine failed");
			}),
		});
		await expect(page.keyboard.type("x")).rejects.toThrow("engine failed");
	});

	it("bad steps reject before anything is sent", async () => {
		const { browser, page } = await attachedPage({
			mouse: custom((_p, _x, _y, { play }) =>
				play([
					["move", 1, 2, 0],
					["move", 1, 2, -1],
				]),
			),
		});
		await expect(page.mouse.move(0, 0)).rejects.toThrow("play() step 1");
		expect(browser.events).toEqual([]);
	});

	it("wraps popups and new contexts, and leaves other browsers alone", async () => {
		const { calls, fn } = recordingMouse();
		const { browser, page } = await attachedPage({ mouse: custom(fn) });
		await page.context().openPage().mouse.move(1, 2);
		(await browser.newContext()).openPage().mouse.move(3, 4);

		const { browser: other, page: otherPage } = await attachedPage({
			keyboard: custom(noop),
		});
		await otherPage.mouse.move(5, 6);
		expect(calls).toEqual([
			[1, 2],
			[3, 4],
		]);
		expect(other.events).toEqual([["mouse.move", 5, 6]]);
		expect(() =>
			attach(browser, { ...allRaw(), mouse: custom(fn) }, "linux"),
		).toThrow("already attached");
	});

	it("attaches to a persistent context's existing pages", async () => {
		const { calls, fn } = recordingMouse();
		const browser = fakeBrowser();
		const context = await browser.newContext();
		const page = context.openPage();
		attach(context, { ...allRaw(), mouse: custom(fn) }, "linux");
		await page.mouse.move(7, 8);
		expect(calls).toEqual([[7, 8]]);
	});

	it("the streams follow the seed", async () => {
		const draws: number[] = [];
		for (const seed of [1, 1, 2]) {
			const { page } = await attachedPage({
				mouse: custom((_p, _x, _y, { rng }) => {
					draws.push(rng());
				}),
				seed,
			});
			await page.mouse.move(0, 0);
		}
		expect(draws[0]).toBe(draws[1]);
		expect(draws[0]).toBe(channelStream(1, "mouse")());
		expect(draws[2]).not.toBe(draws[0]);
	});

	it("warns on a remote connection, which a local one does not", async () => {
		const remote = async (isRemote: boolean) => {
			const browser = fakeBrowser();
			browser._connection = { isRemote: () => isRemote, dispatch: noop };
			const { warnings: caught } = await warnings.recordWarnings(async () =>
				attach(browser, { ...allRaw(), mouse: custom(noop) }, "linux"),
			);
			return caught.some((w) => w.message.includes("round trip"));
		};
		expect(await remote(true)).toBe(true);
		expect(await remote(false)).toBe(false);
	});

	it("an event during a call is not inside that call's engine", async () => {
		// In process, the server answers inside the caller's async context.
		const { calls, fn } = recordingMouse();
		const browser = fakeBrowser();
		let onEvent = () => {};
		browser._connection = {
			isRemote: () => false,
			dispatch: () => onEvent(),
		};
		let first = true;
		attach(
			browser,
			{
				...allRaw(),
				mouse: custom((p, x, y, tools) => {
					if (first) {
						first = false;
						browser._connection.dispatch();
					}
					return fn(p, x, y, tools);
				}),
			},
			"linux",
		);
		const page = await browser.newPage();
		let inner: Promise<unknown> = Promise.resolve();
		onEvent = () => {
			inner = page.mouse.move(1, 2);
		};
		await page.mouse.move(3, 4);
		await inner;
		expect(calls).toEqual([
			[1, 2],
			[3, 4],
		]);
	});
});

describe("play() pacing", () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it("holds its schedule under latency", async () => {
		// 200 steps 10 ms apart against 5 ms of latency per event: a late event
		// delays only itself, so no step starts late and nothing adds up.
		vi.useFakeTimers({ toFake: ["setTimeout", "performance"] });
		let records: { i: number; t_planned: number; t_actual: number }[] = [];
		const { page } = await attachedPage(
			{
				mouse: custom(async (_p, _x, _y, { play }) => {
					records = await play(
						Array.from({ length: 200 }, (_, i) => ["move", i, i, i * 10]),
					);
				}),
			},
			5,
		);
		const start = performance.now();
		let finished = Number.NaN;
		const run = page.mouse.move(1, 1).then(() => {
			finished = performance.now() - start;
		});
		await vi.advanceTimersByTimeAsync(3000);
		await run;
		expect(records).toHaveLength(200);
		expect(records.map((r) => r.t_actual)).toEqual(
			records.map((r) => r.t_planned),
		);
		expect(finished).toBe(1990 + 5);
	});

	it("delays only the step a slow event runs into", async () => {
		vi.useFakeTimers({ toFake: ["setTimeout", "performance"] });
		let records: { t_planned: number; t_actual: number }[] = [];
		const { page } = await attachedPage(
			{
				mouse: custom(async (_p, _x, _y, { play }) => {
					records = await play([
						["move", 0, 0, 0],
						["move", 1, 1, 10],
						["move", 2, 2, 100],
					]);
				}),
			},
			50,
		);
		const run = page.mouse.move(1, 1);
		await vi.advanceTimersByTimeAsync(1000);
		await run;
		expect(records.map((r) => r.t_actual)).toEqual([0, 50, 100]);
	});
});
