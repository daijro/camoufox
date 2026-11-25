/**
 * The driver defaults on playwright-core's real client classes, with no browser:
 * a connection that answers from a fake server, so what these tests read is the
 * protocol messages a browser would get. Against a browser, the behaviour is
 * browser/tests/playwright/patches/driven-fill-paste.py.
 */
import { HIT_TEST_JS, SCROLL_PLAN_JS } from "@jwriter20/myuri";
import { firefox } from "playwright-core";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
	attach as attachHumanize,
	clock,
	FRAME_ORIGIN,
} from "../src/_humanize_playwright.js";
import {
	attachDriverDefaults,
	FILL_NEEDS_CLICK,
} from "../src/driver_defaults.js";
import { myuri, raw } from "../src/humanize.js";

const HIT_TEST = String(HIT_TEST_JS);
const BOX = { x: 40, y: 120, width: 200, height: 24 };

/** A value as Playwright's protocol serializes it. */
function serialized(value: unknown): unknown {
	if (value === null) return { v: "null" };
	if (typeof value === "number") return { n: value };
	if (typeof value === "boolean") return { b: value };
	if (typeof value === "string") return { s: value };
	if (Array.isArray(value)) return { a: value.map(serialized), id: 1 };
	return {
		o: Object.entries(value as object).map(([k, v]) => ({
			k,
			v: serialized(v),
		})),
		id: 1,
	};
}

let guids = 0;

/** A connection whose server answers each call, and the messages it got. */
function client({
	launched = true,
	needsClick = true,
	lands = true,
}: {
	launched?: boolean;
	needsClick?: boolean;
	lands?: boolean;
} = {}) {
	const Connection = (firefox as any)._connection.constructor;
	const connection = new Connection();
	const sent: any[] = [];
	const frameGuid = `frame-${++guids}`;
	const elementGuid = `element-${guids}`;
	let focused = !needsClick;

	const answer = ({ method, params }: any) => {
		if (method === "click") focused = true;
		if (method === "waitForSelector") return { element: { guid: elementGuid } };
		if (method === "boundingBox") return { value: BOX };
		if (method === "screenshot") return { binary: "" };
		if (method !== "evaluateExpression") return {};
		// The hit test answers null, or why a press would miss.
		if (params.expression === HIT_TEST)
			return {
				value: serialized(lands ? null : "<div> intercepts pointer events"),
			};
		// The field, in view in the top window.
		if (params.expression === FRAME_ORIGIN) return { value: serialized(null) };
		if (params.expression === String(SCROLL_PLAN_JS))
			return {
				value: serialized({
					inView: true,
					deltaY: 0,
					hoverX: 500,
					hoverY: 350,
					isPage: true,
					region: BOX,
					box: BOX,
					borders: [0, 0],
				}),
			};
		const answers: Record<string, boolean> = { [FILL_NEEDS_CLICK]: !focused };
		return { value: { b: answers[params.expression] ?? true } };
	};
	connection.onmessage = (message: any) => {
		if (!message.id) return;
		sent.push(message);
		setImmediate(() =>
			connection.dispatch({ id: message.id, result: answer(message) }),
		);
	};

	if (launched) attachDriverDefaults(connection._rootObject);
	const create = (
		parent: string,
		type: string,
		guid: string,
		initializer: any,
	) =>
		connection.dispatch({
			guid: parent,
			method: "__create__",
			params: { type, guid, initializer },
		});
	create("", "Frame", frameGuid, {
		url: "about:blank",
		name: "",
		loadStates: [],
	});
	create(frameGuid, "ElementHandle", elementGuid, { preview: "" });
	return {
		connection,
		// A press on the field, as the page sees a mouse down.
		focus: () => {
			focused = true;
		},
		frame: connection._objects.get(frameGuid),
		handle: connection._objects.get(elementGuid),
		// What the page would see: the plumbing of finding an element is not it.
		calls: () =>
			sent
				.filter((m) => !["waitForSelector", "dispose"].includes(m.method))
				.map((m) =>
					m.method === "evaluateExpression" ? m.params.expression : m.method,
				),
		sent,
	};
}

describe("fill clicks first", () => {
	const CLICKED = [
		FILL_NEEDS_CLICK,
		"scrollIntoViewIfNeeded",
		HIT_TEST,
		"click",
		"fill",
	];

	it("Frame.fill scrolls and clicks a field without focus", async () => {
		const { frame, calls, sent } = client();
		await frame.fill("#a", "x");
		expect(calls()).toEqual(CLICKED);
		const evaluate = sent.find((m) => m.method === "evaluateExpression");
		expect(evaluate.params.isFunction).toBe(true);
		const click = sent.find((m) => m.method === "click");
		expect(click.params.selector).toBe("#a >> nth=0");
		const fill = sent.find((m) => m.method === "fill");
		expect(fill.params).toMatchObject({ selector: "#a", value: "x" });
	});

	it("Locator.fill acts on the strict selector", async () => {
		const { frame, calls, sent } = client();
		await frame.locator("#a").fill("x");
		expect(calls()).toEqual(CLICKED);
		const click = sent.find((m) => m.method === "click");
		expect(click.params).toMatchObject({ selector: "#a", strict: true });
	});

	it("a covered field gets no click, and the fill goes on", async () => {
		const { frame, calls } = client({ lands: false });
		await frame.fill("#a", "x");
		expect(calls()).toEqual([
			FILL_NEEDS_CLICK,
			"scrollIntoViewIfNeeded",
			HIT_TEST,
			"fill",
		]);
	});

	it("a focused field is filled as it is", async () => {
		const { frame, calls } = client({ needsClick: false });
		await frame.fill("#a", "x");
		expect(calls()).toEqual([FILL_NEEDS_CLICK, "fill"]);
	});

	it("passes timeout and force on", async () => {
		const { frame, sent } = client();
		await frame.fill("#a", "x", { timeout: 1234, force: true });
		const click = sent.find((m) => m.method === "click");
		expect(click.params.force).toBe(true);
		expect(click.metadata.timeout).toBe(1234);
	});

	it("ElementHandle.fill does the same", async () => {
		const { handle, calls } = client();
		await handle.fill("x");
		expect(calls()).toEqual(CLICKED);
	});

	it("leaves a browser Camoufox did not launch alone", async () => {
		const { frame, handle, calls } = client({ launched: false });
		await frame.fill("#a", "x");
		await handle.fill("x");
		expect(calls()).toEqual(["fill", "fill"]);
	});
});

describe("screenshot caret", () => {
	it("defaults to initial, and keeps an explicit caret", async () => {
		const { handle, sent } = client();
		await handle.screenshot();
		await handle.screenshot({ caret: "hide" });
		expect(
			sent.filter((m) => m.method === "screenshot").map((m) => m.params.caret),
		).toEqual(["initial", "hide"]);
	});

	it("leaves a browser Camoufox did not launch alone", async () => {
		const { handle, sent } = client({ launched: false });
		await handle.screenshot();
		expect(sent.find((m) => m.method === "screenshot").params.caret).toBe(
			undefined,
		);
	});
});

describe("myuri on the real client", () => {
	// myuri waits on the clock; here a wait only moves the clock on.
	const real = { ...clock };
	beforeEach(() => {
		clock.sleep = async () => {};
	});
	afterEach(() => {
		Object.assign(clock, real);
	});

	// The JS client's Locator calls Frame's public methods, so a Frame method routed
	// to the Locator would call itself without the guard this pins.
	function pageOf(frame: any, input: unknown[][], focus: () => void) {
		const page: any = {
			_timeoutSettings: { timeout: () => ({ timeout: 30000 }) },
			mouse: {
				move: async (x: number, y: number) => input.push(["mouse.move", x, y]),
				down: async () => {
					focus();
					input.push(["mouse.down"]);
				},
				up: async () => input.push(["mouse.up"]),
				wheel: async () => {},
				click: async () => {},
				dblclick: async () => {},
			},
			keyboard: {
				down: async () => {},
				up: async () => {},
				insertText: async () => {},
				type: async () => {},
				press: async () => {},
			},
			evaluate: async () => [1000, 700],
			locator: (selector: string) => frame.locator(selector),
			mainFrame: () => frame,
			context: () => ({}),
		};
		frame._page = page;
		return page;
	}
	// A move part that goes straight to the point myuri chose.
	const attach = ({ frame, focus }: any) => {
		const input: unknown[][] = [];
		const seen: number[][] = [];
		const page = pageOf(frame, input, focus);
		attachHumanize(
			{ on: () => {}, pages: () => [page] },
			{
				mouse: myuri({
					move: (_p, x, y, { play }) => {
						seen.push([x, y]);
						return play([["move", x, y, 0]]);
					},
				}),
				keyboard: raw(),
				scroll: raw(),
			},
			"linux",
		);
		return { page, input, seen };
	};
	const inBox = ([x, y]: number[]) =>
		BOX.x <= x &&
		x <= BOX.x + BOX.width &&
		BOX.y <= y &&
		y <= BOX.y + BOX.height;

	it("Frame.click presses once, at myuri's point", async () => {
		const fake = client();
		const { frame, sent, calls } = fake;
		const { input, seen } = attach(fake);
		await frame.click("#a");
		expect(seen).toHaveLength(1);
		expect(inBox(seen[0])).toBe(true);
		expect(calls()).toContain(HIT_TEST);
		expect(input).toEqual([
			["mouse.move", ...seen[0]],
			["mouse.down"],
			["mouse.up"],
		]);
		expect(sent.filter((m) => m.method === "click")).toEqual([]);
	});

	it("a fill clicks once, through myuri, then fills", async () => {
		const fake = client();
		const { sent, calls } = fake;
		const { page, input, seen } = attach(fake);
		await page.fill("#a", "x");
		expect(seen).toHaveLength(1);
		expect(input.filter(([e]) => e === "mouse.down")).toHaveLength(1);
		expect(sent.filter((m) => m.method === "click")).toEqual([]);
		expect(calls().slice(-2)).toEqual([FILL_NEEDS_CLICK, "fill"]);
	});

	it("Locator.pressSequentially on a page with myuri reaches the server", async () => {
		const fake = client();
		const { frame, sent } = fake;
		attach(fake);
		await frame.locator("#a").pressSequentially("hi");
		expect(sent.filter((m) => m.method === "type")).toHaveLength(1);
	});
});
