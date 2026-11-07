/**
 * The driver defaults on playwright-core's real client classes, with no browser:
 * a connection that answers from a fake server, so what these tests read is the
 * protocol messages a browser would get. Against a browser, the behaviour is
 * browser/tests/playwright/patches/driven-fill-paste.py.
 */
import { firefox } from "playwright-core";
import { describe, expect, it } from "vitest";
import { attachCustom } from "../src/_humanize_custom.js";
import {
	attachDriverDefaults,
	FILL_CLICK_LANDS,
	FILL_NEEDS_CLICK,
} from "../src/driver_defaults.js";
import { custom } from "../src/humanize.js";

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
		if (method === "boundingBox")
			return { value: { x: 40, y: 120, width: 200, height: 24 } };
		if (method === "screenshot") return { binary: "" };
		if (method !== "evaluateExpression") return {};
		const answers: Record<string, boolean> = {
			[FILL_NEEDS_CLICK]: !focused,
			[FILL_CLICK_LANDS]: lands,
		};
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
		FILL_CLICK_LANDS,
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
			FILL_CLICK_LANDS,
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

describe("custom engines on the real client", () => {
	// The JS client's Locator calls Frame's public methods, so a Frame method routed
	// to the Locator would call itself without the guard this pins.
	function pageOf(frame: any, moves: unknown[][]) {
		const page: any = {
			mouse: {
				move: async (x: number, y: number) => moves.push(["mouse.move", x, y]),
				down: async () => {},
				up: async () => {},
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
			locator: (selector: string) => frame.locator(selector),
			mainFrame: () => frame,
			context: () => ({}),
		};
		frame._page = page;
		return page;
	}
	const attach = (frame: any, fn: any) => {
		const moves: unknown[][] = [];
		const page = pageOf(frame, moves);
		attachCustom({ on: () => {}, pages: () => [page] }, { mouse: custom(fn) });
		return { page, moves };
	};

	it("Frame.click reaches the server once, after the engine's move", async () => {
		const { frame, sent } = client();
		const seen: number[][] = [];
		const { moves } = attach(frame, (_p: any, x: number, y: number, t: any) => {
			seen.push([x, y]);
			return t.original();
		});
		await frame.click("#a");
		expect(seen).toEqual([[140, 132]]);
		expect(moves).toEqual([["mouse.move", 140, 132]]);
		const clicks = sent.filter((m) => m.method === "click");
		expect(clicks).toHaveLength(1);
		expect(clicks[0].params.selector).toBe("#a >> nth=0");
	});

	it("a fill clicks once, through the engine, then fills", async () => {
		const { frame, sent, calls } = client();
		const seen: number[][] = [];
		const { page } = attach(frame, (_p: any, x: number, y: number, t: any) => {
			seen.push([x, y]);
			return t.original();
		});
		await page.fill("#a", "x");
		expect(seen).toEqual([[140, 132]]);
		expect(sent.filter((m) => m.method === "click")).toHaveLength(1);
		expect(calls().slice(-2)).toEqual([FILL_NEEDS_CLICK, "fill"]);
	});

	it("Locator.pressSequentially on a page with engines reaches the server", async () => {
		const { frame, sent } = client();
		attach(frame, () => {});
		await frame.locator("#a").pressSequentially("hi");
		expect(sent.filter((m) => m.method === "type")).toHaveLength(1);
	});
});
