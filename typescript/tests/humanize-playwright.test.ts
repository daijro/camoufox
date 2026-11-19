/**
 * myuri on Playwright pages: the parts passed to myuri(), raw() channels and
 * the page wrappers. The twin of python/tests/test_humanize_playwright.py,
 * against the same fake page and the same recorded sequence,
 * browser/tests/humanize/sequence.json.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import {
	HIT_TEST_JS,
	type PartContext,
	SCROLL_PLAN_JS,
} from "@jwriter20/myuri";
import { errors } from "playwright-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	attach,
	clock,
	FRAME_ORIGIN,
	VIEWPORT,
} from "../src/_humanize_playwright.js";
import { FILL_NEEDS_CLICK } from "../src/driver_defaults.js";
import {
	CHANNELS,
	drivenChannels,
	type MyuriOptions,
	myuri,
	normalize,
	raw,
} from "../src/humanize.js";
import { launchServer } from "../src/server.js";
import { NewBrowser } from "../src/sync_api.js";
import * as warnings from "../src/warnings.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SEQUENCE = JSON.parse(
	fs.readFileSync(
		path.resolve(
			HERE,
			"..",
			"..",
			"browser",
			"tests",
			"humanize",
			"sequence.json",
		),
		"utf-8",
	),
);
const SIZE = [1000, 700] as const;

// ---- the fake page ---------------------------------------------------------

type Box = { x: number; y: number; width: number; height: number };

// Where the fake page lays out each selector, in document px. "#framed" is in
// an iframe whose viewport starts at (30, 40) in the page's.
const LAYOUT: Record<string, Box> = {
	"#far": { x: 100, y: 1600, width: 80, height: 30 },
	"#name": { x: 40, y: 120, width: 200, height: 24 },
	"#near": { x: 500, y: 300, width: 50, height: 20 },
	"#framed": { x: 10, y: 10, width: 60, height: 20 },
};
const FRAME = [30, 40] as const;

/** A browser whose calls record what reaches Playwright. Each has its own
 * Locator and Frame classes, like Playwright's, so patching one stays here. */
function fakeBrowser() {
	const events: unknown[][] = [];
	const log = (...event: unknown[]) => {
		events.push(event);
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
		private log(name: string, ...args: unknown[]) {
			log(`locator.${name}`, this.selector, ...args);
		}
		/** The border box in its frame's viewport. */
		box(): Box {
			const box = { ...LAYOUT[this.selector] } as Box;
			if (this.selector !== "#framed") box.y -= this.owner.scrollY;
			return box;
		}
		async click(o: any = {}) {
			if (!o.trial) {
				this.owner.toggle(this.selector);
				this.owner.focused = this.selector;
			}
			this.log("click", o.position ?? null);
		}
		async dblclick(o: any = {}) {
			this.log("dblclick", o.position ?? null);
		}
		async hover(o: any = {}) {
			this.log("hover", o.position ?? null);
		}
		async check(o: any = {}) {
			this.log("check", o.position ?? null);
		}
		async uncheck(o: any = {}) {
			this.log("uncheck", o.position ?? null);
		}
		async fill(value: string) {
			this.log("fill", value);
		}
		async type(text: string) {
			this.log("type", text);
		}
		async pressSequentially(text: string) {
			this.log("pressSequentially", text);
		}
		async press(key: string) {
			this.log("press", key);
		}
		async scrollIntoViewIfNeeded() {
			const box = this.box();
			if (box.y < 0 || box.y + box.height > SIZE[1])
				this.owner.scrollY += box.y + box.height / 2 - SIZE[1] / 2;
			this.log("scrollIntoViewIfNeeded");
		}
		async selectText() {
			this.owner.focused = this.selector;
			this.log("selectText");
		}
		async focus() {
			this.owner.focused = this.selector;
			this.log("focus");
		}
		async isChecked() {
			return this.owner.checked.has(this.selector);
		}
		async boundingBox() {
			const box = this.box();
			if (this.selector === "#framed") {
				box.x += FRAME[0];
				box.y += FRAME[1];
			}
			return box;
		}
		async evaluate(fn: any, arg?: any) {
			const page = this.owner;
			if (String(fn) === FRAME_ORIGIN)
				return this.selector === "#framed"
					? [this.box().x, this.box().y]
					: null;
			if (fn === SCROLL_PLAN_JS) return this.plan(arg);
			if (fn === HIT_TEST_JS) {
				// What covers the point at each press, until the list runs out.
				page.aimed = this.selector;
				return page.covered.shift() ?? null;
			}
			if (String(fn) === FILL_NEEDS_CLICK)
				return page.focused !== this.selector;
			throw new Error(`unexpected page function ${String(fn).slice(0, 40)}`);
		}
		private plan(arg: any) {
			const box = this.box();
			const top = Math.max(box.y, 0);
			const bottom = Math.min(box.y + box.height, SIZE[1]);
			return {
				inView: box.y >= 0 && box.y + box.height <= SIZE[1],
				deltaY: box.y + box.height / 2 - SIZE[1] * arg.finishPosition,
				hoverX: SIZE[0] / 2,
				hoverY: SIZE[1] / 2,
				isPage: true,
				region: bottom <= top ? null : { ...box, y: top, height: bottom - top },
				box,
				borders: [2, 3],
			};
		}
	}

	/** Page and Frame methods that take a selector. */
	class SelectorMethods {
		protected call(_name: string, _selector: string, ..._args: unknown[]) {}
		async click(selector: string, _o?: any) {
			this.call("click", selector);
		}
		async dblclick(selector: string, _o?: any) {
			this.call("dblclick", selector);
		}
		async hover(selector: string, _o?: any) {
			this.call("hover", selector);
		}
		async check(selector: string, _o?: any) {
			this.call("check", selector);
		}
		async uncheck(selector: string, _o?: any) {
			this.call("uncheck", selector);
		}
		async fill(selector: string, value: string, _o?: any) {
			this.call("fill", selector, value);
		}
		async type(selector: string, text: string, _o?: any) {
			this.call("type", selector, text);
		}
		async press(selector: string, key: string, _o?: any) {
			this.call("press", selector, key);
		}
	}

	class FakeFrame extends SelectorMethods {
		constructor(readonly owner: FakePage) {
			super();
		}
		page() {
			return this.owner;
		}
		locator(selector: string) {
			return this.owner.locator(selector);
		}
		protected call(name: string, selector: string, ...args: unknown[]) {
			log(`page.frame.${name}`, selector, ...args);
		}
	}

	class FakePage extends SelectorMethods {
		covered: string[] = [];
		checked = new Set<string>();
		aimed: string | null = null;
		focused: string | null = null;
		scrollY = 0;
		timeout = 30000;
		// Playwright's client keeps the default timeout here.
		_timeoutSettings = { timeout: () => ({ timeout: this.timeout }) };
		private readonly frame = new FakeFrame(this);
		readonly mouse = {
			move: async (x: number, y: number) => log("mouse.move", x, y),
			down: async (o: any = {}) =>
				log("mouse.down", o.button ?? "left", o.clickCount ?? 1),
			up: async (o: any = {}) => {
				if (this.aimed) {
					this.toggle(this.aimed);
					this.focused = this.aimed;
				}
				log("mouse.up", o.button ?? "left", o.clickCount ?? 1);
			},
			wheel: async (dx: number, dy: number) => {
				this.scrollY += dy;
				log("mouse.wheel", dx, dy);
			},
			click: async (x: number, y: number) => log("mouse.click", x, y),
			dblclick: async (x: number, y: number) => log("mouse.dblclick", x, y),
		};
		readonly keyboard = {
			down: async (key: string) => log("keyboard.down", key),
			up: async (key: string) => log("keyboard.up", key),
			insertText: async (text: string) => log("keyboard.insertText", text),
			type: async (text: string) => log("keyboard.type", text),
			press: async (key: string) => log("keyboard.press", key),
		};
		constructor(readonly owner: FakeContext) {
			super();
		}
		context() {
			return this.owner;
		}
		mainFrame() {
			return this.frame;
		}
		locator(selector: string) {
			return new FakeLocator(this, selector);
		}
		toggle(selector: string) {
			if (!this.checked.delete(selector)) this.checked.add(selector);
		}
		async evaluate(fn: any) {
			expect(String(fn)).toBe(VIEWPORT);
			return [...SIZE];
		}
		protected call(name: string, selector: string, ...args: unknown[]) {
			log(`page.${name}`, selector, ...args);
		}
	}

	class FakeContext {
		readonly opened: FakePage[] = [];
		private handlers: ((page: FakePage) => void)[] = [];
		on(event: string, handler: (page: FakePage) => void) {
			expect(event).toBe("page");
			this.handlers.push(handler);
		}
		pages() {
			return this.opened;
		}
		/** A page the browser opened by itself, such as a popup. */
		openPage() {
			const page = new FakePage(this);
			this.opened.push(page);
			for (const handler of this.handlers) handler(page);
			return page;
		}
	}

	const made: FakeContext[] = [];
	return {
		events,
		_connection: undefined as any,
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
	};
}

// myuri waits on the clock; here a wait only moves the clock on.
const real = { ...clock };
beforeEach(() => {
	let now = 0;
	clock.now = () => now;
	clock.sleep = async (ms) => {
		now += ms;
	};
});
afterEach(() => {
	Object.assign(clock, real);
});

const allRaw = () => Object.fromEntries(CHANNELS.map((c) => [c, raw()]));

/** A page whose channels are raw() except those `humanize` names. */
async function attachedPage(humanize: Record<string, unknown>, seed = 7) {
	const browser = fakeBrowser();
	attach(browser, { ...allRaw(), seed, ...humanize }, "linux");
	return { browser, page: (await browser.newPage()) as any };
}

const names = (browser: { events: unknown[][] }) =>
	browser.events.map((e) => e[0]);

const inBox = (x: number, y: number, box: Box) =>
	box.x <= x && x <= box.x + box.width && box.y <= y && y <= box.y + box.height;

const moves = (browser: { events: unknown[][] }) =>
	browser.events.filter((e) => e[0] === "mouse.move") as [
		string,
		number,
		number,
	][];

/** A mouse whose move part records where it was sent. */
function recording() {
	const seen: number[][] = [];
	return {
		seen,
		mouse: myuri({
			move: (_p, x, y) => {
				seen.push([x, y]);
			},
		}),
	};
}

// ---- the shared scenario ---------------------------------------------------

/** Parts that draw from the stream and play, in place of myuri's timing
 * (which follows the clock). myuri still scrolls, aims and checks the hits. */
function scenarioParts() {
	const at = { x: 0, y: 0 };
	const parts: MyuriOptions = {
		move: (_page, x, y, { rng, play }) => {
			const n = 2 + Math.floor(rng() * 3);
			const { x: sx, y: sy } = at;
			Object.assign(at, { x, y });
			return play(
				Array.from({ length: n }, (_, i) => [
					"move",
					sx + ((x - sx) * (i + 1)) / n,
					sy + ((y - sy) * (i + 1)) / n,
					i + 1,
				]),
			);
		},
		press: (_page, button, _count, { rng, play }) =>
			play([
				["down", button, 0],
				["up", button, 1 + Math.floor(rng() * 3)],
			]),
		wheel: (_page, dx, dy, { rng, play }) => {
			const n = 2 + Math.floor(rng() * 2);
			return play(
				Array.from({ length: n }, (_, i) => ["wheel", dx / n, dy / n, i]),
			);
		},
		type: (_page, text, { rng, play }) => {
			const steps: any[] = [];
			let t = 0;
			for (const ch of text) {
				steps.push(["key", ch, "down", t]);
				t += 1 + Math.floor(rng() * 3);
				steps.push(["key", ch, "up", t]);
			}
			return play(steps);
		},
		// A Playwright call inside a part is Playwright's own.
		key: (page, key) => page.keyboard.press(key),
	};
	return {
		mouse: myuri({ move: parts.move, press: parts.press }),
		keyboard: myuri({ type: parts.type, key: parts.key }),
		scroll: myuri({ wheel: parts.wheel }),
	};
}

async function scenario() {
	const { browser, page } = await attachedPage(scenarioParts(), 1234);
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
	return browser.events;
}

describe("the scenario", () => {
	it("matches the sequence the Python launcher recorded", async () => {
		expect(await scenario()).toEqual(SEQUENCE.events);
	});
});

// ---- myuri's own parts -----------------------------------------------------

describe("myuri", () => {
	it("moves to a point in the box and clicks there", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		await page.locator("#near").click();
		const last = moves(browser).at(-1) as [string, number, number];
		expect(moves(browser).length).toBeGreaterThan(1);
		expect(names(browser)).not.toContain("locator.click");
		expect(inBox(last[1], last[2], LAYOUT["#near"])).toBe(true);
		expect(browser.events.slice(-2)).toEqual([
			["mouse.down", "left", 1],
			["mouse.up", "left", 1],
		]);
	});

	it("reaches into an iframe at its offset", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		await page.locator("#framed").click();
		const [, x, y] = moves(browser).at(-1) as [string, number, number];
		const framed = LAYOUT["#framed"];
		expect(
			inBox(x, y, {
				...framed,
				x: framed.x + FRAME[0],
				y: framed.y + FRAME[1],
			}),
		).toBe(true);
	});

	it("wheels an element into view in mouse notches", async () => {
		const { browser, page } = await attachedPage({
			mouse: myuri(),
			scroll: myuri(),
		});
		await page.locator("#far").click();
		const wheels = browser.events.filter((e) => e[0] === "mouse.wheel");
		// A Linux or Windows mouse wheel scrolls in 100 px notches (docs/input-dispatch.md).
		expect(wheels.length).toBeGreaterThan(0);
		for (const [, dx, dy] of wheels as [string, number, number][]) {
			expect(dx).toBe(0);
			expect(dy !== 0 && dy % 100 === 0).toBe(true);
		}
		const [, x, y] = moves(browser).at(-1) as [string, number, number];
		const far = LAYOUT["#far"];
		expect(inBox(x, y, { ...far, y: far.y - page.scrollY })).toBe(true);
	});

	it("reaches for a covered point again", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		page.covered = ["<div> intercepts pointer events"];
		await page.locator("#near").click();
		expect(names(browser).filter((n) => n === "mouse.down")).toHaveLength(1);
		expect(page.covered).toEqual([]);
	});

	it("skips the check on a forced press", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		page.covered = ["<div> intercepts pointer events"];
		await page.locator("#near").click({ force: true });
		expect(names(browser).filter((n) => n === "mouse.down")).toHaveLength(1);
		expect(page.covered).toHaveLength(1);
	});

	it("raises as Playwright does for a point covered past the timeout", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		page.covered = Array(100).fill("<div> intercepts pointer events");
		const click = page.locator("#near").click({ timeout: 300 });
		await expect(click).rejects.toThrow(errors.TimeoutError);
		await expect(click).rejects.toThrow(
			/^Timeout 300ms exceeded: click <div> intercepts pointer events$/,
		);
		expect(names(browser)).not.toContain("mouse.down");
	});

	it("hovers with the move alone", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		await page.locator("#near").hover();
		expect(names(browser)).toContain("mouse.move");
		for (const name of ["mouse.down", "mouse.up", "locator.hover"])
			expect(names(browser)).not.toContain(name);
	});

	it("checks only when the state differs, and frames take the locator flow", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		await page.check("#near");
		await page.check("#near");
		await page.mainFrame().click("#near");
		expect(names(browser).filter((n) => n === "mouse.down")).toHaveLength(2);
		expect(page.checked.has("#near")).toBe(false);
	});

	it("makes the click before a fill", async () => {
		const { browser, page } = await attachedPage({ mouse: myuri() });
		await page.fill("#name", "text");
		expect(names(browser)).toContain("mouse.move");
		expect(names(browser).slice(-2)).toEqual(["mouse.up", "locator.fill"]);
	});

	it("types into the field it selected", async () => {
		const { browser, page } = await attachedPage({
			keyboard: myuri({ wpm: 200 }),
		});
		await page.fill("#name", "hi");
		const kinds = names(browser);
		// With a raw mouse the click before the fill is Playwright's.
		expect(kinds.indexOf("locator.click")).toBeLessThan(
			kinds.indexOf("locator.selectText"),
		);
		expect(kinds.indexOf("locator.selectText")).toBeLessThan(
			kinds.indexOf("keyboard.down"),
		);
		// What the field holds, with myuri's typos corrected as it corrects them.
		let field = "";
		for (const [kind, key] of browser.events as [string, string][])
			if (kind === "keyboard.down" || kind === "keyboard.insertText")
				field = key === "Backspace" ? field.slice(0, -1) : field + key;
		expect(field).toBe("hi");
	});

	it("follows the seed", async () => {
		const clicked = async (seed: number) => {
			const { browser, page } = await attachedPage({ mouse: myuri() }, seed);
			await page.locator("#near").click();
			return moves(browser);
		};
		expect(await clicked(1)).toEqual(await clicked(1));
		expect(await clicked(1)).not.toEqual(await clicked(2));
	});
});

// ---- parts and raw() channels ----------------------------------------------

describe("parts", () => {
	it("get the page and can call myuri's through default", async () => {
		const seen: unknown[][] = [];
		const { browser, page } = await attachedPage({
			mouse: myuri({
				move: (p, x, y, { default: myuris }: PartContext<void>) => {
					seen.push([p, x, y]);
					return myuris();
				},
			}),
		});
		await page.mouse.move(50, 60);
		expect(seen).toEqual([[page, 50, 60]]);
		expect(moves(browser).at(-1)).toEqual(["mouse.move", 50, 60]);
	});

	it("reach Playwright when they call their own channel", async () => {
		const { browser, page } = await attachedPage({
			mouse: myuri({
				move: async (p, x, y) => {
					await p.mouse.move(x - 1, y - 1);
					return p.mouse.move(x, y);
				},
			}),
		});
		await page.mouse.move(50, 60);
		expect(browser.events).toEqual([
			["mouse.move", 49, 59],
			["mouse.move", 50, 60],
		]);
	});

	it("an intoView part is the scroll a click uses", async () => {
		const scrolled: string[] = [];
		const { browser, page } = await attachedPage({
			mouse: myuri(),
			scroll: myuri({
				intoView: (_p, locator) => {
					scrolled.push(locator.selector);
					return locator.scrollIntoViewIfNeeded();
				},
			}),
		});
		await page.locator("#far").click();
		expect(new Set(scrolled)).toEqual(new Set(["#far"]));
		expect(names(browser)).not.toContain("mouse.wheel");
		expect(names(browser).filter((n) => n === "mouse.down")).toHaveLength(1);
	});

	it("a raw scroll is Playwright's, and a raw mouse is one move", async () => {
		const mouse = await attachedPage({ mouse: myuri() });
		await mouse.page.locator("#far").click();
		expect(names(mouse.browser)).toContain("locator.scrollIntoViewIfNeeded");
		expect(names(mouse.browser)).not.toContain("mouse.wheel");

		const scroll = await attachedPage({ scroll: myuri() });
		await scroll.page.locator("#far").click();
		const kinds = names(scroll.browser);
		// myuri wheels over the scroller, reached in one move, then Playwright clicks.
		expect(kinds[0]).toBe("mouse.move");
		expect(kinds.filter((n) => n === "mouse.move")).toHaveLength(1);
		expect(kinds.at(-1)).toBe("locator.click");
		expect(kinds).toContain("mouse.wheel");
	});

	it("propagate exceptions", async () => {
		const { page } = await attachedPage({
			keyboard: myuri({
				type: () => {
					throw new Error("part failed");
				},
			}),
		});
		await expect(page.keyboard.type("x")).rejects.toThrow("part failed");
	});
});

describe("attach", () => {
	it("wraps popups and new contexts, and leaves other browsers alone", async () => {
		const { seen, mouse } = recording();
		const { browser, page } = await attachedPage({ mouse });
		await page.context().openPage().mouse.move(1, 2);
		await (await browser.newContext()).openPage().mouse.move(3, 4);
		const other = await attachedPage({ keyboard: myuri() });
		await other.page.mouse.move(5, 6);
		expect(seen).toEqual([
			[1, 2],
			[3, 4],
		]);
		expect(other.browser.events).toEqual([["mouse.move", 5, 6]]);
		expect(() =>
			attach(browser, { ...allRaw(), mouse: myuri() }, "linux"),
		).toThrow("already attached");
	});

	it("attaches to a persistent context's existing pages", async () => {
		const { seen, mouse } = recording();
		const context = await fakeBrowser().newContext();
		const page = context.openPage();
		attach(context, { ...allRaw(), mouse }, "linux");
		await page.mouse.move(7, 8);
		expect(seen).toEqual([[7, 8]]);
	});

	it("warns on a remote connection, which a local one does not", async () => {
		const remote = async (isRemote: boolean) => {
			const browser = fakeBrowser();
			browser._connection = { isRemote: () => isRemote, dispatch: () => {} };
			const { warnings: caught } = await warnings.recordWarnings(async () =>
				attach(browser, { ...allRaw(), mouse: myuri() }, "linux"),
			);
			return caught.some((w) => w.message.includes("round trip"));
		};
		expect(await remote(true)).toBe(true);
		expect(await remote(false)).toBe(false);
	});

	it("an event during a call is not inside that call's part", async () => {
		// In process, the server answers inside the caller's async context.
		const { seen, mouse } = recording();
		const browser = fakeBrowser();
		let onEvent = () => {};
		browser._connection = { isRemote: () => false, dispatch: () => onEvent() };
		let first = true;
		const move = mouse.options.move as NonNullable<MyuriOptions["move"]>;
		attach(
			browser,
			{
				...allRaw(),
				mouse: myuri({
					move: (p, x, y, ctx) => {
						if (first) {
							first = false;
							browser._connection.dispatch();
						}
						return move(p, x, y, ctx);
					},
				}),
			},
			"linux",
		);
		const page: any = await browser.newPage();
		let inner: Promise<unknown> = Promise.resolve();
		onEvent = () => {
			inner = page.mouse.move(1, 2);
		};
		await page.mouse.move(3, 4);
		await inner;
		expect(seen).toEqual([
			[1, 2],
			[3, 4],
		]);
	});
});

// ---- the setting -----------------------------------------------------------

describe("the setting", () => {
	it("names the channels an engine drives", () => {
		expect(
			drivenChannels({ mouse: myuri(), keyboard: raw(), scroll: raw() }),
		).toEqual(["mouse"]);
		expect(drivenChannels({ mouse: raw() })).toEqual(["keyboard", "scroll"]);
		expect(drivenChannels(null)).toEqual([]);
	});

	it("refuses a channel set to null; an omitted one is myuri", () => {
		expect(() => normalize({ mouse: null })).toThrow(
			'humanize["mouse"]=None is not an engine',
		);
		expect(normalize({}).engines.mouse.engine).toBe("myuri");
		expect(normalize({ seed: null }).seed).toBeUndefined();
	});

	it("NewBrowser attaches the parts to what it launched", async () => {
		const browser = fakeBrowser();
		const launch = vi.fn(async () => browser);
		const { seen, mouse } = recording();
		const launched: any = await NewBrowser({ launch } as any, {
			from_options: { headless: true },
			humanize: { mouse, keyboard: raw(), scroll: raw() },
		});
		await (await launched.newPage()).mouse.move(1, 2);
		expect(seen).toEqual([[1, 2]]);
	});

	it("NewBrowser checks the setting before it launches", async () => {
		const launch = vi.fn();
		await expect(
			NewBrowser({ launch } as any, {
				from_options: { headless: true },
				humanize: { mouse: { engine: "myuri", options: { move: 1 } } },
			}),
		).rejects.toThrow("takes the function that replaces the part");
		expect(launch).not.toHaveBeenCalled();
	});

	it("launchServer refuses humanize", async () => {
		await expect(
			launchServer({ humanize: { mouse: myuri() } }),
		).rejects.toThrow("launch_server() cannot run humanize engines");
	});
});
