/**
 * Driver calls that reach the page as a person's actions would. The TypeScript
 * twin of python/src/camoufox/driver_defaults.py, which holds the reasoning.
 *
 * Screenshots default to caret: "initial", which leaves the page's style
 * attributes alone. fill() clicks a text field that is not focused first, unless
 * something covers it. Both apply only under a Browser or BrowserContext marked
 * by a Camoufox launch (attachDriverDefaults).
 */

const LAUNCHED = Symbol.for("camoufox.driver-defaults");
const FILL_PATCHED = Symbol.for("camoufox.driver-defaults.fill");

// The next two strings are byte-identical to the Python constants
// (tests/package-parity.test.ts).

// Whether fill() on this target should click first: a text field a person types
// into, without focus. fill() on a label, or inside one, fills its control.
export const FILL_NEEDS_CLICK = `(e) => {
  const field = e.matches('a, input, textarea, button, select') || e.isContentEditable
    ? e : (e.closest('label')?.control || e);
  const type = field.localName === 'input' ? field.type : null;
  const typed = field.localName === 'textarea' || field.isContentEditable ||
    ['text', 'search', 'email', 'url', 'tel', 'password', 'number'].includes(type);
  if (!typed || field.disabled || field.readOnly)
    return false;
  const active = field.getRootNode().activeElement;
  return active !== field && !(field.isContentEditable && field.contains(active));
}`;

// Why a press at a point of the target would miss it, or null when it lands on
// the target, its label's control, or the button or link it is in. `at` is
// [dx, dy] into the target's box (its middle when absent), and a third true
// entry also misses a disabled target.
export const PRESS_MISSES = `(e, at) => {
  const field = e.closest('label')?.control || e;
  const target = e.matches('input, textarea, select') ? e : e.closest('button, [role=button], a, [role=link]') || e;
  if (at?.[2] && (target.matches(':disabled') || target.closest('[aria-disabled="true"]')))
    return 'element is not enabled';
  const r = e.getBoundingClientRect();
  const [x, y] = at ? [r.left + at[0], r.top + at[1]] : [r.left + r.width / 2, r.top + r.height / 2];
  let hit = e.ownerDocument.elementFromPoint(x, y);
  while (hit?.shadowRoot) {
    const inner = hit.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === hit)
      break;
    hit = inner;
  }
  for (let n = hit; n; n = n.parentNode || n.host) {
    if (n === e || n === target || n === field || n.control === field)
      return null;
  }
  return hit ? '<' + hit.localName + '> intercepts pointer events' : 'element is not at the point';
}`;

/**
 * The JS client sends a string as an expression and does not call what it
 * evaluates to (isFunction: false), where Python's lets the page decide. A
 * function whose source is the string is sent and called.
 */
export function pageFunction(source: string): () => unknown {
	return Object.assign(() => undefined, { toString: () => source });
}

async function clickToFocus(
	target: any,
	evaluate: (script: () => unknown) => Promise<unknown>,
	{ timeout, force }: Record<string, any>,
): Promise<void> {
	if (await evaluate(pageFunction(FILL_NEEDS_CLICK))) {
		await target.scrollIntoViewIfNeeded({ timeout });
		if ((await evaluate(pageFunction(PRESS_MISSES))) === null)
			await target.click({ timeout, force });
	}
}

/** Page, Locator and Frame fill (and Locator.clear) all go through Frame.fill. */
export function patchFrameFill(prototype: any): void {
	if (Object.hasOwn(prototype, FILL_PATCHED)) return;
	prototype[FILL_PATCHED] = true;
	const original = prototype.fill;
	prototype.fill = async function (
		selector: string,
		value: string,
		options: Record<string, any> = {},
	) {
		if (launchedByCamoufox(this)) {
			const locator = this.locator(selector);
			const target = options.strict ? locator : locator.first();
			await clickToFocus(
				target,
				(script) =>
					target.evaluate(script, undefined, { timeout: options.timeout }),
				options,
			);
		}
		return original.call(this, selector, value, options);
	};
}

function patchHandleFill(prototype: any): void {
	if (Object.hasOwn(prototype, FILL_PATCHED)) return;
	prototype[FILL_PATCHED] = true;
	const original = prototype.fill;
	prototype.fill = async function (
		value: string,
		options: Record<string, any> = {},
	) {
		if (launchedByCamoufox(this))
			await clickToFocus(this, (script) => this.evaluate(script), options);
		return original.call(this, value, options);
	};
}

/** playwright-core does not export its client classes, so they are taken from
 * the objects its connection creates. */
function patchClientClass(object: any): void {
	if (object._type === "Frame") patchFrameFill(Object.getPrototypeOf(object));
	if (object._type === "ElementHandle")
		patchHandleFill(Object.getPrototypeOf(object));
}

/**
 * Give every page under `target` (a Browser or BrowserContext from a Camoufox
 * launch) these defaults. The caret is filled in where the client sends the
 * request, so page, element and locator screenshots all get it; an explicit
 * caret is kept.
 */
export function attachDriverDefaults<T>(target: T): T {
	const owner = target as any;
	owner[LAUNCHED] = true;
	const connection = owner._connection;
	if (!connection || connection[LAUNCHED]) return target;
	connection[LAUNCHED] = true;

	const send = connection.sendMessageToServer;
	connection.sendMessageToServer = function (
		object: any,
		method: string,
		params: Record<string, any>,
		...rest: any[]
	) {
		if (
			method === "screenshot" &&
			params?.caret === undefined &&
			launchedByCamoufox(object)
		)
			params = { ...params, caret: "initial" };
		return send.call(this, object, method, params, ...rest);
	};

	// A persistent context arrives with its pages, and so its frames, created.
	for (const object of connection._objects.values()) patchClientClass(object);
	const create = connection._createRemoteObject;
	connection._createRemoteObject = function (...args: any[]) {
		const object = create.apply(this, args);
		patchClientClass(object);
		return object;
	};
	return target;
}

/** ElementHandle -> Frame -> Page -> BrowserContext -> Browser. */
function launchedByCamoufox(object: any): boolean {
	for (let owner = object; owner; owner = owner._parent)
		if (owner[LAUNCHED]) return true;
	return false;
}
