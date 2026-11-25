/**
 * myuri's smart actions on Playwright pages. The TypeScript twin of
 * python/src/camoufox/_humanize_playwright.py; both are held to the sequence
 * in browser/tests/humanize/sequence.json.
 *
 * Each page of the browser (or persistent context) a humanize setting is
 * attached to gets one myuri `Actions`. It owns the timing and motion of the
 * page's input and the decisions around a click: scroll the element into
 * view, choose the point, check that a press there lands, and try again when
 * it does not. The host below sends each event through Playwright's own input
 * methods, so the page sees the same trusted events as from any Playwright
 * call, and the browser runs every channel raw.
 *
 * A raw() channel's parts are Playwright's: its moves are one event, its
 * scroll into view is Playwright's. A part passed to myuri() is called with
 * the page in place of the host. Inside it, Playwright calls are Playwright's
 * own, so page.mouse.move in a move part moves the mouse once.
 *
 * What is wrapped, per page, and the channel that drives it:
 *
 *     mouse     Mouse.move / click / dblclick; Page/Frame/Locator click,
 *               dblclick, hover, check and uncheck, and the click that focuses
 *               a field before fill
 *     keyboard  Keyboard.type / press; Page/Frame/Locator fill, type, press,
 *               and Locator.pressSequentially
 *     scroll    Mouse.wheel; Locator.scrollIntoViewIfNeeded, and the scroll
 *               into view before a pointer action, fill, type or
 *               pressSequentially
 *
 * ElementHandle methods, tap, dragAndDrop and dragTo are Playwright's own. An
 * ElementHandle cannot be measured and moved to as a Locator can, and a drag's
 * moves happen inside Playwright's server.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
import {
	Actions,
	type DeepPartial,
	generateProfile,
	HIT_TEST_JS,
	type Host,
	Missed,
	type MyuriSettings,
	makeRng,
	type Parts,
} from "@jwriter20/myuri";
import { errors } from "playwright-core";
import {
	FILL_NEEDS_CLICK,
	pageFunction,
	patchFrameFill,
} from "./driver_defaults.js";
import {
	CHANNELS,
	type Channel,
	type Engine,
	type HumanizeSetting,
	normalize,
} from "./humanize.js";
import type { OsName } from "./utils.js";
import { LeakWarning } from "./warnings.js";

/**
 * `inPart`: a part of the caller's is running; its Playwright calls are
 * Playwright's.
 *
 * `inPlaywright`: inside one of Playwright's own methods. In Python the
 * client's methods call an inner layer no wrapper sits on. In the JS client
 * they call each other's public methods (Locator.click calls Frame.click,
 * Mouse.dblclick calls Mouse.click), so those calls must reach Playwright too.
 *
 * `timeout`: the action's, for the host's page reads.
 */
interface Scope {
	inPart: boolean;
	inPlaywright: boolean;
	timeout?: number;
}
const scope = new AsyncLocalStorage<Scope>();
const within = <R>(change: Partial<Scope>, fn: () => R): R =>
	scope.run(
		{ inPart: false, inPlaywright: false, ...scope.getStore(), ...change },
		fn,
	);

const SETUP = Symbol.for("camoufox.humanize");
const ACTIONS = Symbol.for("camoufox.humanize-actions");
const ROUTED_FRAMES = Symbol.for("camoufox.humanize-routed");
const DISPATCH_ISOLATED = Symbol.for("camoufox.humanize-dispatch");

// Byte-identical to the Python constants (tests/package-parity.test.ts).
export const VIEWPORT = "() => [innerWidth, innerHeight]";
// The element's client origin in its frame, or null in the top window, whose
// viewport is the page's.
export const FRAME_ORIGIN =
	"e => { if (window === window.top) return null; const r = e.getBoundingClientRect(); return [r.x, r.y]; }";

type Original = (...args: any[]) => Promise<any>;
type Options = Record<string, any>;
type Flow = (
	setup: Setup,
	actions: Actions<any>,
	locator: any,
	original: Original,
	args: any[],
) => Promise<any> | null;

/** The clock myuri's waits are on. */
export const clock = {
	now: () => performance.now(),
	sleep: (ms: number) => new Promise((resolve) => setTimeout(resolve, ms)),
};

/** `fn` as Playwright's own: a call it makes on a wrapped method passes through. */
function direct<F extends Original>(fn: F): F {
	return ((...args: any[]) =>
		within({ inPlaywright: true }, () => fn(...args))) as F;
}

/** myuri's host on one page: every event is a Playwright input call. */
function host(page: any): Host<any> {
	const { mouse, keyboard } = page;
	const down = direct(mouse.down.bind(mouse));
	const up = direct(mouse.up.bind(mouse));
	const timeout = () => scope.getStore()?.timeout;
	return {
		move: direct(mouse.move.bind(mouse)),
		click: async (button, clickCount, holdMs) => {
			await down({ button, clickCount });
			await clock.sleep(holdMs);
			await up({ button, clickCount });
		},
		down: (button) => down({ button }),
		up: (button) => up({ button }),
		wheel: direct(mouse.wheel.bind(mouse)),
		keyDown: direct(keyboard.down.bind(keyboard)),
		keyUp: direct(keyboard.up.bind(keyboard)),
		insertText: direct(keyboard.insertText.bind(keyboard)),
		evaluate: (target, fn, arg) =>
			target.evaluate(fn, arg, { timeout: timeout() }),
		offset: async (target) => {
			const origin = await target.evaluate(
				pageFunction(FRAME_ORIGIN),
				undefined,
				{ timeout: timeout() },
			);
			if (origin === null) return [0, 0];
			const box = await target.boundingBox({ timeout: timeout() });
			return box ? [box.x - origin[0], box.y - origin[1]] : null;
		},
		viewport: () => page.evaluate(pageFunction(VIEWPORT)),
		now: () => clock.now(),
		sleep: (ms) => clock.sleep(ms),
	};
}

// ---- parts -----------------------------------------------------------------

const LOCATOR_ORIGINALS = new WeakMap<object, Record<string, Original>>();

function locatorOriginal(locator: any, name: string): Original {
	return (
		LOCATOR_ORIGINALS.get(locator.constructor) as Record<string, Original>
	)[name];
}

// What myuri calls for a raw() channel: the parts its other channels' flows use.
const RAW_PARTS: Record<Channel, Parts<any>> = {
	mouse: { move: (_host, x, y, { play }) => play([["move", x, y, 0]]) },
	keyboard: {},
	scroll: {
		intoView: (_host, locator) =>
			locatorOriginal(locator, "scrollIntoViewIfNeeded")(locator, {
				timeout: scope.getStore()?.timeout,
			}),
	},
};

class Setup {
	// One stream for every page, so two pages never replay the same draws.
	readonly rng: () => number;

	// One person for the whole browser, drawn from the seed around the settings.
	readonly settings: MyuriSettings;

	constructor(
		readonly engines: Record<Channel, Engine>,
		seed: number,
		settings: DeepPartial<MyuriSettings>,
		readonly os: OsName,
	) {
		this.rng = makeRng(seed);
		// Camoufox identities point with a mouse unless told otherwise.
		const scroll = { device: "mouse" as const, ...settings.scroll };
		this.settings = generateProfile(seed, { ...settings, scroll }, os);
	}

	/** Whether myuri drives the channel for the call being made. */
	drives(channel: Channel): boolean {
		const current = scope.getStore();
		return (
			this.engines[channel].engine === "myuri" &&
			!current?.inPart &&
			!current?.inPlaywright
		);
	}

	actions(page: any): Actions<any> {
		const parts: Record<string, unknown> = {};
		for (const channel of CHANNELS) {
			const { engine, options } = this.engines[channel];
			if (engine === "raw") Object.assign(parts, RAW_PARTS[channel]);
			// A part of the caller's, called with the page in place of the host;
			// one that throws rejects, as Playwright's methods do.
			else
				for (const [name, fn] of Object.entries(options))
					parts[name] = async (_host: unknown, ...args: unknown[]) =>
						within({ inPart: true }, () =>
							(fn as (...a: unknown[]) => unknown)(page, ...args),
						);
		}
		return new Actions(host(page), this.rng, {
			os: this.os,
			settings: this.settings,
			parts,
		});
	}
}

// ---- flows -----------------------------------------------------------------

const timed = <R>(timeout: number | undefined, fn: () => Promise<R>) =>
	within({ timeout }, fn);

function timeoutOf(locator: any, options: Options): number {
	return options.timeout ?? locator.page()._timeoutSettings.timeout({}).timeout;
}

/** myuri's click (or, for hover, its move) onto the locator, failing as
 * Playwright's action does: a timeout naming why the point was never reached. */
async function reach(
	actions: Actions<any>,
	locator: any,
	name: string,
	options: Options,
	timeout: number,
): Promise<void> {
	try {
		await actions.click(locator, {
			button: options.button ?? "left",
			clickCount: options.clickCount ?? (name === "dblclick" ? 2 : 1),
			modifiers: options.modifiers ?? [],
			position: options.position,
			force: Boolean(options.force),
			press: name !== "hover",
			// 0 is no timeout, as in Playwright.
			timeout,
		});
	} catch (error) {
		if (!(error instanceof Missed)) throw error;
		throw new errors.TimeoutError(
			`Timeout ${timeout}ms exceeded: ${name} ${error.message}`,
		);
	}
}

/** click / dblclick / hover / check / uncheck. */
function pointer(name: string): Flow {
	return (setup, actions, locator, original, [options = {}]) => {
		if (options.trial || !(setup.drives("mouse") || setup.drives("scroll")))
			return null;
		const timeout = timeoutOf(locator, options);
		const mouse = setup.drives("mouse");
		return timed(timeout, async () => {
			if (!mouse) {
				await actions.intoView(locator);
				return original(locator, options);
			}
			const checkbox = name === "check" || name === "uncheck";
			if (
				checkbox &&
				(await locator.isChecked({ timeout })) === (name === "check")
			)
				return;
			await reach(actions, locator, name, options, timeout);
			if (
				checkbox &&
				(await locator.isChecked({ timeout })) !== (name === "check")
			)
				throw new Error(
					`Clicking the checkbox did not change its state (${name})`,
				);
		});
	};
}

/** The click before a fill (driver_defaults), with myuri's move when it drives
 * the mouse. The fill then finds the field focused. */
async function clickToFocus(
	setup: Setup,
	actions: Actions<any>,
	locator: any,
	options: Options,
) {
	const timeout = timeoutOf(locator, options);
	if (
		!(await locator.evaluate(pageFunction(FILL_NEEDS_CLICK), undefined, {
			timeout,
		}))
	)
		return;
	await actions.intoView(locator);
	if ((await locator.evaluate(HIT_TEST_JS, null, { timeout })) !== null) return;
	if (setup.drives("mouse"))
		await reach(actions, locator, "click", { force: options.force }, timeout);
	else
		await locatorOriginal(locator, "click")(locator, {
			timeout,
			force: options.force,
		});
}

/** fill / type / pressSequentially / press on a locator. */
function keys(kind: "fill" | "type" | "press"): Flow {
	return (setup, actions, locator, original, [text, options = {}]) => {
		const keyboard = setup.drives("keyboard");
		const scroll = kind !== "press" && setup.drives("scroll");
		const mouse = kind === "fill" && setup.drives("mouse");
		if (!(keyboard || mouse || scroll)) return null;
		return timed(options.timeout, async () => {
			if (scroll) await actions.intoView(locator);
			if (kind === "fill") await clickToFocus(setup, actions, locator, options);
			if (!keyboard || text === "") return original(locator, text, options);
			const { timeout, force } = options;
			// Typing then replaces what the field held, as fill() does.
			if (kind === "fill") await locator.selectText({ force, timeout });
			else await locator.focus({ timeout });
			return kind === "press" ? actions.key(text) : actions.type(text);
		});
	};
}

const scrollLocator: Flow = (
	setup,
	actions,
	locator,
	_original,
	[options = {}],
) =>
	setup.drives("scroll")
		? timed(options.timeout, () => actions.intoView(locator))
		: null;

const LOCATOR_FLOWS: Record<string, Flow> = {
	click: pointer("click"),
	dblclick: pointer("dblclick"),
	hover: pointer("hover"),
	check: pointer("check"),
	uncheck: pointer("uncheck"),
	fill: keys("fill"),
	type: keys("type"),
	pressSequentially: keys("type"),
	press: keys("press"),
	scrollIntoViewIfNeeded: scrollLocator,
};

/** Route a Locator class's input methods through myuri on the locator's page.
 * A page with no humanize setting (any other browser) gets the original. */
function patchLocatorClass(cls: any): void {
	if (LOCATOR_ORIGINALS.has(cls)) return;
	const originals: Record<string, Original> = {};
	LOCATOR_ORIGINALS.set(cls, originals);
	for (const [name, flow] of Object.entries(LOCATOR_FLOWS)) {
		const original = cls.prototype[name];
		originals[name] = direct((locator: any, ...args: any[]) =>
			original.apply(locator, args),
		);
		cls.prototype[name] = function (...args: any[]) {
			const page = this.page();
			const setup: Setup | undefined = page?.[SETUP];
			if (!setup) return original.apply(this, args);
			return (
				flow(setup, page[ACTIONS], this, originals[name], args) ??
				originals[name](this, ...args)
			);
		};
	}
}

// Page and Frame methods that take a selector, routed to the Locator method of
// the same name when myuri drives one of these channels.
const PAGE_ROUTES: Record<string, Channel[]> = {
	click: ["mouse", "scroll"],
	dblclick: ["mouse", "scroll"],
	hover: ["mouse", "scroll"],
	check: ["mouse", "scroll"],
	uncheck: ["mouse", "scroll"],
	fill: ["mouse", "keyboard", "scroll"],
	type: ["keyboard", "scroll"],
	press: ["keyboard"],
};
const ROUTES_WITH_TEXT = ["fill", "type", "press"];

const myuriOn = (setup: Setup | undefined, channels: Channel[]) =>
	channels.some((channel) => setup?.engines[channel].engine === "myuri");

function routed(owner: any, name: string): Original {
	const texts = ROUTES_WITH_TEXT.includes(name) ? 1 : 0;
	return (selector: string, ...rest: any[]) => {
		const { strict, ...options } = rest[texts] ?? {};
		const locator = owner.locator(selector);
		// Without strict, Page and Frame methods act on the first match.
		return (strict ? locator : locator.first())[name](
			...rest.slice(0, texts),
			options,
		);
	};
}

function attachPage(page: any, setup: Setup): void {
	if (page[SETUP]) return;
	const actions = setup.actions(page);
	page[ACTIONS] = actions;
	page[SETUP] = setup;
	patchLocatorClass(page.locator("html").constructor);
	const { mouse, keyboard } = page;
	const o = {
		move: direct(mouse.move.bind(mouse)),
		click: direct(mouse.click.bind(mouse)),
		dblclick: direct(mouse.dblclick.bind(mouse)),
		wheel: direct(mouse.wheel.bind(mouse)),
		type: direct(keyboard.type.bind(keyboard)),
		press: direct(keyboard.press.bind(keyboard)),
	};

	mouse.move = (x: number, y: number, options?: Options) => {
		if (setup.drives("mouse")) return actions.move(x, y);
		actions.moved(x, y);
		return o.move(x, y, options);
	};
	const clicking =
		(original: Original, double: boolean): Original =>
		(x: number, y: number, options: Options = {}) => {
			if (!setup.drives("mouse")) {
				actions.moved(x, y);
				return original(x, y, options);
			}
			const count = double ? 2 : (options.clickCount ?? 1);
			return actions.clickAt(x, y, options.button ?? "left", count);
		};
	mouse.click = clicking(o.click, false);
	mouse.dblclick = clicking(o.dblclick, true);
	// A delay is myuri's to plan.
	mouse.wheel = (dx: number, dy: number) =>
		setup.drives("scroll") ? actions.wheel(dx, dy) : o.wheel(dx, dy);
	keyboard.type = (text: string, options?: Options) =>
		setup.drives("keyboard") ? actions.type(text) : o.type(text, options);
	keyboard.press = (key: string, options?: Options) =>
		setup.drives("keyboard") ? actions.key(key) : o.press(key, options);

	// page.click(selector) and friends: the same flow as the locator's.
	for (const [name, channels] of Object.entries(PAGE_ROUTES))
		if (myuriOn(setup, channels)) page[name] = routed(page, name);
	patchFrameClass(Object.getPrototypeOf(page.mainFrame()));
}

/** Route a Frame class's input methods as a page's are, for frames of a page
 * where myuri drives one of the channels. */
function patchFrameClass(prototype: any): void {
	if (Object.hasOwn(prototype, ROUTED_FRAMES)) return;
	prototype[ROUTED_FRAMES] = true;
	// Fill's click-first hook stays inside this routing, whichever came first,
	// so myuri plans a fill's click once.
	patchFrameFill(prototype);
	for (const [name, channels] of Object.entries(PAGE_ROUTES)) {
		const original = prototype[name];
		prototype[name] = function (...args: any[]) {
			if (
				scope.getStore()?.inPlaywright ||
				!myuriOn(this.page()?.[SETUP], channels)
			)
				return original.apply(this, args);
			return routed(this, name)(...args);
		};
	}
}

function attachContext(context: any, setup: Setup): void {
	if (context[SETUP]) return;
	context[SETUP] = setup;
	context.on("page", (page: any) => attachPage(page, setup));
	for (const page of context.pages()) attachPage(page, setup);
}

/**
 * In process, Playwright's server answers inside the caller's async context, so
 * an event handler (a popup's, say) would inherit the scope of whichever wrapped
 * call was in flight.
 */
function isolateDispatch(connection: any): void {
	if (!connection || connection[DISPATCH_ISOLATED]) return;
	connection[DISPATCH_ISOLATED] = true;
	const { dispatch } = connection;
	connection.dispatch = function (...args: any[]) {
		return scope.exit(() => dispatch.apply(this, args));
	};
}

/**
 * Run myuri on every page of `target`, a Browser or BrowserContext, including
 * pages and contexts opened later, as the `humanize` setting says. Other
 * browsers in this process are untouched. `os` ("macos", "windows" or
 * "linux") is the launch identity's, whose people myuri plans for.
 * Camoufox()/NewBrowser() call this themselves; for one from `connect()`,
 * launch it without humanize.
 *
 * Every draw comes from one stream, of `humanize.seed` or a random seed, and
 * the seed draws the person myuri plays around `humanize.settings`.
 */
export function attach<T>(
	target: T,
	humanize: HumanizeSetting,
	os: OsName,
	iKnowWhatImDoing?: boolean,
): T {
	const { engines, seed, settings } = normalize(humanize);
	if (CHANNELS.every((channel) => engines[channel].engine === "raw"))
		return target;
	const owner = target as any;
	if (owner[SETUP])
		throw new Error("humanize is already attached to this browser");
	if (owner._connection?.isRemote())
		LeakWarning.warn("humanize_remote", iKnowWhatImDoing);
	isolateDispatch(owner._connection);

	const setup = new Setup(
		engines,
		seed ?? randomBytes(4).readUInt32BE(),
		settings,
		os,
	);

	if (typeof owner.newContext !== "function") {
		// A BrowserContext (a persistent context).
		attachContext(owner, setup);
		return target;
	}

	owner[SETUP] = setup;
	for (const context of owner.contexts()) attachContext(context, setup);
	const then: Record<string, (made: any) => any> = {
		newContext: (context) => {
			attachContext(context, setup);
			return context;
		},
		newPage: (page) => {
			attachContext(page.context(), setup);
			attachPage(page, setup);
			return page;
		},
	};
	for (const [name, attach] of Object.entries(then)) {
		const original = owner[name];
		owner[name] = async (...args: any[]) =>
			attach(await original.apply(owner, args));
	}
	return target;
}
