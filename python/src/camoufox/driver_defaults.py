"""Driver calls that reach the page as a person's actions would.

Screenshots leave the page alone.

Playwright hides the text caret for a screenshot unless told caret="initial":
from its utility world it sets `caret-color: transparent !important` in the
style attribute of every input, textarea and contenteditable element, then puts
the old value back. A page sees each change with a MutationObserver, reads the
transparent caret while the capture runs, and is left with a `style` attribute
on elements that had none (docs/input-dispatch.md, "Screenshots").

Firefox's capture (drawSnapshot) never paints the caret, so hiding it changes
nothing in the image. A screenshot of a page Camoufox launched defaults to
caret="initial"; a caller who passes caret= still gets what they ask for.

fill() clicks the field first. Playwright focuses the field by script and
inserts the text (Page.insertText, which Juggler pastes): the page gets focus
with no pointer or mouse event before it, where a person clicks the field
first. A text field that is not focused is clicked (Playwright's click: the
mouse moves there and presses, through the OS-path dispatch) before the fill;
a focused one is pasted into as it is. Fields fill() sets without pasting
(date, color, range, ...) are left alone. So is a field something covers: a
person cannot click it either, and fill() itself needs no click.
"""

from typing import Any

_MARK = '_camoufox_driver_defaults'


def mark(target: Any) -> Any:
    """Give every page under `target` (a Browser or BrowserContext from a
    Camoufox launch) these defaults."""
    setattr(getattr(target, '_impl_obj', target), _MARK, True)
    _install()
    return target


def _launched_by_camoufox(owner: Any) -> bool:
    # ElementHandle -> Frame -> Page -> BrowserContext -> Browser
    while owner is not None:
        if getattr(owner, _MARK, False):
            return True
        owner = getattr(owner, '_parent', None)
    return False


def _with_caret_default(original: Any) -> Any:
    async def screenshot(self: Any, *args: Any, **kwargs: Any) -> bytes:
        if kwargs.get('caret') is None and _launched_by_camoufox(self):
            kwargs['caret'] = 'initial'
        return await original(self, *args, **kwargs)

    setattr(screenshot, _MARK, True)
    screenshot.__wrapped__ = original  # type: ignore[attr-defined]
    return screenshot


# Whether fill() on this target should click first: a text field a person types
# into, without focus. fill() on a label, or inside one, fills its control.
FILL_NEEDS_CLICK = """(e) => {
  const field = e.matches('a, input, textarea, button, select') || e.isContentEditable
    ? e : (e.closest('label')?.control || e);
  const type = field.localName === 'input' ? field.type : null;
  const typed = field.localName === 'textarea' || field.isContentEditable ||
    ['text', 'search', 'email', 'url', 'tel', 'password', 'number'].includes(type);
  if (!typed || field.disabled || field.readOnly)
    return false;
  const active = field.getRootNode().activeElement;
  return active !== field && !(field.isContentEditable && field.contains(active));
}"""

# Whether a click at the middle of the target reaches it, or its label.
FILL_CLICK_LANDS = """(e) => {
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
}"""


async def _click_to_focus(target: Any, evaluate: Any, timeout: Any, force: Any) -> None:
    if await evaluate(FILL_NEEDS_CLICK):
        await target.scroll_into_view_if_needed(timeout=timeout)
        if await evaluate(FILL_CLICK_LANDS):
            await target.click(timeout=timeout, force=force)


def _frame_fill_clicks_first(original: Any) -> Any:
    async def _fill(self: Any, selector: str, *args: Any, **kwargs: Any) -> None:
        if _launched_by_camoufox(self):
            target = self.locator(selector)
            if not kwargs.get('strict'):
                target = target.first
            timeout = kwargs.get('timeout')

            def evaluate(script: str) -> Any:
                return target.evaluate(script, timeout=timeout)

            await _click_to_focus(target, evaluate, timeout, kwargs.get('force'))
        return await original(self, selector, *args, **kwargs)

    setattr(_fill, _MARK, True)
    _fill.__wrapped__ = original  # type: ignore[attr-defined]
    return _fill


def _handle_fill_clicks_first(original: Any) -> Any:
    async def fill(self: Any, *args: Any, **kwargs: Any) -> None:
        if _launched_by_camoufox(self):
            await _click_to_focus(self, self.evaluate, kwargs.get('timeout'), kwargs.get('force'))
        return await original(self, *args, **kwargs)

    setattr(fill, _MARK, True)
    fill.__wrapped__ = original  # type: ignore[attr-defined]
    return fill


def _install() -> None:
    # Locator.screenshot goes through ElementHandle.screenshot; Page, Locator
    # and Frame fill (and Locator.clear) through Frame._fill, or Frame.fill.
    from playwright._impl._element_handle import ElementHandle
    from playwright._impl._frame import Frame
    from playwright._impl._page import Page

    for cls in (Page, ElementHandle):
        if not getattr(cls.screenshot, _MARK, False):
            cls.screenshot = _with_caret_default(cls.screenshot)
    # Playwright before 1.54 has no Frame._fill: every fill goes through Frame.fill.
    name = '_fill' if hasattr(Frame, '_fill') else 'fill'
    if not getattr(getattr(Frame, name), _MARK, False):
        setattr(Frame, name, _frame_fill_clicks_first(getattr(Frame, name)))
    if not getattr(ElementHandle.fill, _MARK, False):
        ElementHandle.fill = _handle_fill_clicks_first(ElementHandle.fill)
