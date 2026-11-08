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

// Whether a click at the middle of the target reaches it, or its label.
export const FILL_CLICK_LANDS = `(e) => {
  const field = e.closest('label')?.control || e;
  const r = e.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  let hit = e.ownerDocument.elementFromPoint(x, y);
  while (hit?.shadowRoot) {
    const inner = hit.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === hit)
      break;
    hit = inner;
  }
  for (; hit; hit = hit.parentNode || hit.host) {
    if (hit === e || hit === field || hit.control === field)
      return true;
  }
  return false;
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
		if (await evaluate(pageFunction(FILL_CLICK_LANDS)))
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
