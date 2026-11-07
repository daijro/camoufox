/**
 * Client-side humanize engines: `custom(fn)` on a channel. The TypeScript twin
 * of python/src/camoufox/_humanize_custom.py; both are held to the sequence in
 * browser/tests/humanize/custom-sequence.json.
 *
 * The function runs in this process, never in the browser. It plans a channel's
 * input and plays it through Playwright's own input methods, so the page sees
 * the same trusted events as from any Playwright call. The browser runs that
 * channel raw (humanizeConfig), so input is never humanized twice.
 *
 * What is wrapped, per page of the browser (or persistent context) it is
 * attached to, and what the function is called for:
 *
 *     mouse     Mouse.move / click / dblclick; the move to the click point of
 *               Page/Frame/Locator click, dblclick, hover, check and uncheck,
 *               and of the click that focuses a field before fill
 *     keyboard  Keyboard.type / press; Page/Frame/Locator fill, type, press,
 *               and Locator.pressSequentially
 *     scroll    Mouse.wheel; Locator.scrollIntoViewIfNeeded, and the scroll into
 *               view before a Page/Frame/Locator click, dblclick, hover, check,
 *               uncheck, fill, type or pressSequentially when the element is
 *               not in view
 *
 * ElementHandle methods, tap, dragAndDrop and dragTo are Playwright's own. An
 * ElementHandle cannot be scrolled and moved to in the flows below, and a drag's
 * moves happen inside Playwright's server.
 *
 * Playwright runs an action inside its own server, so a client wrapper cannot
 * reach into it. The wrappers act first: they scroll the element into view and
 * move to the point, so Playwright's own scroll finds nothing to do and its own
 * move has no distance to cover.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
import { inspect } from "node:util";
import {
	FILL_CLICK_LANDS,
	FILL_NEEDS_CLICK,
	pageFunction,
	patchFrameFill,
} from "./driver_defaults.js";
import {
	type Channel,
	type CustomEngine,
	channelStream,
	customEngines,
	type EngineTools,
	type HumanizeSetting,
	normalize,
	type SeededRng,
} from "./humanize.js";
import { LeakWarning } from "./warnings.js";

/**
 * `active`: the channels whose function is running here. A call a function makes
 * on its own channel (page.mouse.move inside a mouse engine) goes straight to
 * Playwright instead of back into the function.
 *
 * `inPlaywright`: inside one of Playwright's own methods. In Python the client's
 * methods call an inner layer no wrapper sits on. In the JS client they call each
 * other's public methods (Locator.click calls Frame.click, Mouse.dblclick calls
 * Mouse.click), so those calls must reach Playwright too.
 */
interface Scope {
	active: ReadonlySet<Channel>;
	inPlaywright: boolean;
}
const scope = new AsyncLocalStorage<Scope>();

const ENGINES = Symbol.for("camoufox.custom-engines");
const ORIGINALS = Symbol.for("camoufox.custom-originals");
const ROUTED_FRAMES = Symbol.for("camoufox.custom-routed");
const DISPATCH_ISOLATED = Symbol.for("camoufox.custom-dispatch");

// Is the element's box inside its frame's viewport?
export const IN_VIEW = `e => {
  const r = e.getBoundingClientRect();
  return r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth;
}`;
const BORDERS = "e => [e.clientLeft, e.clientTop]";

const BUTTONS = ["left", "right", "middle"];

type Original = (...args: any[]) => Promise<any>;
type Options = Record<string, any>;
type Flow = (
	engines: Engines,
	locator: any,
	original: Original,
	args: any[],
) => Promise<any> | null;

class Engines {
	readonly rng: Partial<Record<Channel, SeededRng>> = {};

	constructor(
		readonly fns: Partial<Record<Channel, CustomEngine>>,
		seed: number | bigint,
	) {
		for (const channel of Object.keys(fns) as Channel[])
			this.rng[channel] = channelStream(seed, channel);
	}

	/** The channel's function, or undefined when it has none or is already running. */
	fn(channel: Channel): CustomEngine | undefined {
		const current = scope.getStore();
		if (current?.inPlaywright || current?.active.has(channel)) return undefined;
		return this.fns[channel];
	}
}

/** `fn` as Playwright's own: a call it makes on a wrapped method passes through. */
function direct<F extends Original>(fn: F): F {
	return ((...args: any[]) =>
		scope.run(
			{ active: scope.getStore()?.active ?? new Set(), inPlaywright: true },
			() => fn(...args),
		)) as F;
}

/** Call the channel's function, with its own channel passed through. */
async function call(
	engines: Engines,
	channel: Channel,
	page: any,
	args: any[],
	original: Original,
	extra: Partial<EngineTools> = {},
): Promise<any> {
	const active = new Set(scope.getStore()?.active);
	active.add(channel);
	return scope.run({ active, inPlaywright: false }, () =>
		(engines.fns[channel] as CustomEngine)(page, ...args, {
			original,
			rng: engines.rng[channel],
			play: (steps: unknown) => play(page, steps),
			...extra,
		}),
	);
}

// ---- play(): schedule-paced dispatch ---------------------------------------

function isNumber(value: unknown): value is number {
	return typeof value === "number" && Number.isFinite(value);
}

/**
 * The steps of a play() call as [kind, values, t], or an Error naming the first
 * bad step. Nothing is dispatched unless every step is valid.
 *
 *     ["move", x, y, t]   ["down", button, t]   ["up", button, t]
 *     ["wheel", dx, dy, t]   ["key", key, "down" | "up", t]   ["text", text, t]
 *
 * t is milliseconds from the start of the call, non-decreasing.
 */
export function validateSteps(steps: any): [string, any[], number][] {
	if (
		typeof steps === "string" ||
		typeof steps?.[Symbol.iterator] !== "function"
	)
		throw new Error(`play() takes a list of steps, got ${inspect(steps)}`);
	const arities: Record<string, number> = {
		move: 3,
		down: 2,
		up: 2,
		wheel: 3,
		key: 3,
		text: 2,
	};
	const plan: [string, any[], number][] = [];
	let last = 0;
	let i = -1;
	for (const step of steps) {
		i += 1;
		const bad = (why: string) =>
			new Error(`play() step ${i} ${inspect(step)}: ${why}`);
		if (!Array.isArray(step) || typeof step[0] !== "string")
			throw bad('a step is an array such as ["move", x, y, t]');
		const [kind, ...args] = step;
		if (!Object.hasOwn(arities, kind))
			throw bad("the kind must be move, down, up, wheel, key or text");
		if (args.length !== arities[kind])
			throw bad(`${kind} takes ${arities[kind]} values after the kind`);
		const t = args[args.length - 1];
		const values = args.slice(0, -1);
		if (!isNumber(t) || t < 0)
			throw bad("t must be a finite number of milliseconds, at least 0");
		if (t < last) throw bad(`t goes back in time (${t} after ${last})`);
		last = t;
		if ((kind === "move" || kind === "wheel") && !values.every(isNumber))
			throw bad(`${kind} takes finite numbers`);
		if ((kind === "down" || kind === "up") && !BUTTONS.includes(values[0]))
			throw bad(`the button must be one of ${BUTTONS.join(", ")}`);
		if (
			kind === "key" &&
			(typeof values[0] !== "string" ||
				!values[0] ||
				!["down", "up"].includes(values[1]))
		)
			throw bad('key takes a key name and "down" or "up"');
		if (kind === "text" && typeof values[0] !== "string")
			throw bad("text takes a string");
		plan.push([kind, values, t]);
	}
	return plan;
}

/** Dispatch each step at start + t on a monotonic clock, so a late round trip
 * delays only its own step and never accumulates. */
async function play(page: any, steps: unknown) {
	const plan = validateSteps(steps);
	const o = page[ORIGINALS];
	const record = [];
	const start = performance.now();
	for (const [i, [kind, values, t]] of plan.entries()) {
		// A timer may fire up to a millisecond early, so wait until the step is due.
		for (
			let wait = start + t - performance.now();
			wait > 0;
			wait = start + t - performance.now()
		)
			await new Promise((resolve) => setTimeout(resolve, wait));
		const actual = performance.now() - start;
		if (kind === "move") await o.move(values[0], values[1]);
		else if (kind === "down") await o.down({ button: values[0] });
		else if (kind === "up") await o.up({ button: values[0] });
		else if (kind === "wheel") await o.wheel(values[0], values[1]);
		else if (kind === "key")
			await (values[1] === "down" ? o.keyDown : o.keyUp)(values[0]);
		else await o.insertText(values[0]);
		record.push({ i, t_planned: t, t_actual: actual });
	}
	return record;
}

// ---- flows -----------------------------------------------------------------

function moveTo(engines: Engines, page: any, x: number, y: number) {
	const { move } = page[ORIGINALS];
	return call(
		engines,
		"mouse",
		page,
		[x, y],
		(nx = x, ny = y, options?: Options) => move(nx, ny, options),
	);
}

const LOCATOR_ORIGINALS = new WeakMap<object, Record<string, Original>>();

function locatorOriginal(locator: any, name: string): Original {
	return (
		LOCATOR_ORIGINALS.get(locator.constructor) as Record<string, Original>
	)[name];
}

async function scrollIntoView(
	engines: Engines,
	locator: any,
	timeout: number | undefined,
	ifNeeded: boolean,
) {
	if (
		ifNeeded &&
		(await locator.evaluate(pageFunction(IN_VIEW), undefined, { timeout }))
	)
		return;
	const scroll = locatorOriginal(locator, "scrollIntoViewIfNeeded");
	return call(
		engines,
		"scroll",
		locator.page(),
		[locator],
		(options?: Options) => scroll(locator, { timeout, ...options }),
	);
}

/** click / dblclick / hover: scroll into view, move to the point, then
 * Playwright's own action, whose move is then zero-length. */
const pointer: Flow = (engines, locator, original, [options = {}]) => {
	const mouse = engines.fn("mouse");
	const scroll = engines.fn("scroll");
	if (!(mouse || scroll) || options.trial) return null;
	return (async () => {
		const { timeout, position } = options;
		if (scroll) await scrollIntoView(engines, locator, timeout, true);
		if (mouse) {
			if (!scroll)
				// The point must be on screen; the browser's scroll engine plans this.
				await locatorOriginal(locator, "scrollIntoViewIfNeeded")(locator, {
					timeout,
				});
			const box = await locator.boundingBox({ timeout });
			if (box) {
				let x = box.x + box.width / 2;
				let y = box.y + box.height / 2;
				if (position) {
					// position is relative to the padding box
					const [left, top] = await locator.evaluate(
						pageFunction(BORDERS),
						undefined,
						{ timeout },
					);
					x = box.x + left + position.x;
					y = box.y + top + position.y;
				}
				await moveTo(engines, locator.page(), x, y);
			}
		}
		return original(locator, options);
	})();
};

/** The click before a fill (driver_defaults), with the mouse engine's move. The
 * fill's own hook then finds the field focused. */
async function clickToFocus(engines: Engines, locator: any, options: Options) {
	const { timeout, force } = options;
	const evaluate = (source: string) =>
		locator.evaluate(pageFunction(source), undefined, { timeout });
	if (!(await evaluate(FILL_NEEDS_CLICK))) return;
	await locatorOriginal(locator, "scrollIntoViewIfNeeded")(locator, {
		timeout,
	});
	if (await evaluate(FILL_CLICK_LANDS)) {
		const original = locatorOriginal(locator, "click");
		const click = { timeout, force };
		await (pointer(engines, locator, original, [click]) ??
			original(locator, click));
	}
}

/** fill / type / pressSequentially / press on a locator. */
function keys(kind: "fill" | "type" | "press"): Flow {
	return (engines, locator, original, [text, options = {}]) => {
		const keyboard = engines.fn("keyboard");
		const scroll = kind === "press" ? undefined : engines.fn("scroll");
		const mouse = kind === "fill" ? engines.fn("mouse") : undefined;
		if (!(keyboard || mouse || scroll)) return null;
		return (async () => {
			const { timeout, force } = options;
			if (scroll) await scrollIntoView(engines, locator, timeout, true);
			if (mouse || (keyboard && kind === "fill"))
				await clickToFocus(engines, locator, options);
			if (!keyboard || text === "") return original(locator, text, options);
			// Typing then replaces what the field held, as fill() does.
			if (kind === "fill") await locator.selectText({ force, timeout });
			else await locator.focus({ timeout });
			return call(
				engines,
				"keyboard",
				locator.page(),
				[text],
				(value = text) => original(locator, value, options),
				{ kind },
			);
		})();
	};
}

const scrollLocator: Flow = (engines, locator, _original, [options = {}]) =>
	engines.fn("scroll")
		? scrollIntoView(engines, locator, options.timeout, false)
		: null;

const LOCATOR_FLOWS: Record<string, Flow> = {
	click: pointer,
	dblclick: pointer,
	hover: pointer,
	check: pointer,
	uncheck: pointer,
	fill: keys("fill"),
	type: keys("type"),
	pressSequentially: keys("type"),
	press: keys("press"),
	scrollIntoViewIfNeeded: scrollLocator,
};

/** Route a Locator class's input methods through the custom engines of the
 * locator's page. A page with none (any other browser) gets the original. */
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
			const engines: Engines | undefined = this.page()?.[ENGINES];
			if (!engines) return original.apply(this, args);
			return (
				flow(engines, this, originals[name], args) ??
				originals[name](this, ...args)
			);
		};
	}
}

// Page and Frame methods that take a selector, routed to the Locator method of
// the same name when one of these channels has a custom engine.
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

function attachPage(page: any, engines: Engines): void {
	if (page[ENGINES]) return;
	const { mouse, keyboard } = page;
	const o = {
		move: direct(mouse.move.bind(mouse)),
		down: direct(mouse.down.bind(mouse)),
		up: direct(mouse.up.bind(mouse)),
		wheel: direct(mouse.wheel.bind(mouse)),
		click: direct(mouse.click.bind(mouse)),
		dblclick: direct(mouse.dblclick.bind(mouse)),
		type: direct(keyboard.type.bind(keyboard)),
		press: direct(keyboard.press.bind(keyboard)),
		keyDown: direct(keyboard.down.bind(keyboard)),
		keyUp: direct(keyboard.up.bind(keyboard)),
		insertText: direct(keyboard.insertText.bind(keyboard)),
	};
	page[ORIGINALS] = o;
	page[ENGINES] = engines;
	patchLocatorClass(page.locator("html").constructor);

	const passthroughUnless =
		(channel: Channel, original: Original, flow: Original): Original =>
		(...args) =>
			engines.fn(channel) ? flow(...args) : original(...args);

	if (engines.fns.mouse) {
		const clickAt =
			(name: "click" | "dblclick"): Original =>
			async (x, y, options) => {
				await moveTo(engines, page, x, y);
				return o[name](x, y, options);
			};
		mouse.move = passthroughUnless("mouse", o.move, (x, y, options) =>
			call(engines, "mouse", page, [x, y], (nx = x, ny = y, more?: Options) =>
				o.move(nx, ny, { ...options, ...more }),
			),
		);
		mouse.click = passthroughUnless("mouse", o.click, clickAt("click"));
		mouse.dblclick = passthroughUnless(
			"mouse",
			o.dblclick,
			clickAt("dblclick"),
		);
	}

	if (engines.fns.scroll)
		mouse.wheel = passthroughUnless("scroll", o.wheel, (dx, dy) =>
			call(engines, "scroll", page, [[dx, dy]], (nx = dx, ny = dy) =>
				o.wheel(nx, ny),
			),
		);

	if (engines.fns.keyboard) {
		const typing =
			(name: "type" | "press"): Original =>
			(text, options) =>
				call(
					engines,
					"keyboard",
					page,
					[text],
					(value = text) => o[name](value, options),
					{ kind: name },
				);
		keyboard.type = passthroughUnless("keyboard", o.type, typing("type"));
		keyboard.press = passthroughUnless("keyboard", o.press, typing("press"));
	}

	// page.click(selector) and friends: the same flow as the locator's.
	for (const [name, channels] of Object.entries(PAGE_ROUTES))
		if (channels.some((channel) => engines.fns[channel]))
			page[name] = routed(page, name);
	patchFrameClass(Object.getPrototypeOf(page.mainFrame()));
}

/** Route a Frame class's input methods as a page's are, for frames of a page with
 * custom engines on one of the channels. */
function patchFrameClass(prototype: any): void {
	if (Object.hasOwn(prototype, ROUTED_FRAMES)) return;
	prototype[ROUTED_FRAMES] = true;
	// Fill's click-first hook stays inside this routing, whichever came first, so
	// the engines plan a fill's click once.
	patchFrameFill(prototype);
	for (const [name, channels] of Object.entries(PAGE_ROUTES)) {
		const original = prototype[name];
		prototype[name] = function (...args: any[]) {
			const engines: Engines | undefined = this.page()?.[ENGINES];
			if (
				scope.getStore()?.inPlaywright ||
				!channels.some((channel) => engines?.fns[channel])
			)
				return original.apply(this, args);
			return (routed(this, name) as any)(...args);
		};
	}
}

function attachContext(context: any, engines: Engines): void {
	if (context[ENGINES]) return;
	context[ENGINES] = engines;
	context.on("page", (page: any) => attachPage(page, engines));
	for (const page of context.pages()) attachPage(page, engines);
}

/**
 * In process, Playwright's server answers inside the caller's async context, so
 * an event handler (a popup's, say) would inherit the scope of whichever wrapped
 * call was in flight and skip the engines.
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
 * Run the custom() engines of `humanize` on every page of `target`, a Browser or
 * BrowserContext, including pages and contexts opened later. Other browsers in
 * this process are untouched. Camoufox()/NewBrowser() call this themselves; for
 * one from `connect()`, launch it with raw() on those channels.
 *
 * The streams use `humanize.seed`, or a random seed.
 */
export function attachCustom<T>(
	target: T,
	humanize: HumanizeSetting,
	iKnowWhatImDoing?: boolean,
): T {
	const fns = customEngines(humanize);
	if (!Object.keys(fns).length) return target;
	const owner = target as any;
	if (owner[ENGINES])
		throw new Error(
			"custom humanize engines are already attached to this browser",
		);
	if (owner._connection?.isRemote())
		LeakWarning.warn("humanize_custom_remote", iKnowWhatImDoing);
	isolateDispatch(owner._connection);

	const seed = normalize(humanize).seed ?? randomBytes(8).readBigUInt64BE();
	const engines = new Engines(fns, seed);

	if (typeof owner.newContext !== "function") {
		// A BrowserContext (a persistent context).
		attachContext(owner, engines);
		return target;
	}

	owner[ENGINES] = engines;
	for (const context of owner.contexts()) attachContext(context, engines);
	const then: Record<string, (made: any) => any> = {
		newContext: (context) => {
			attachContext(context, engines);
			return context;
		},
		newPage: (page) => {
			attachContext(page.context(), engines);
			attachPage(page, engines);
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
