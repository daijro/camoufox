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
types the text (Page.insertText, which Juggler types key by key): the page gets
focus with no pointer or mouse event before it, where a person clicks the
field first. A text field that is not focused is clicked (Playwright's click:
the mouse moves there and presses, through the OS-path dispatch) before the
fill; a focused one is typed into as it is. Fields fill() sets without typing
(date, color, range, ...) are left alone.
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


# Whether a fill() target is a text field a person types into, and whether it
# already has focus.
_FILL_TARGET = """(e) => {
  const active = e.ownerDocument.activeElement;
  const type = e.localName === 'input' ? (e.getAttribute('type') || 'text').toLowerCase() : null;
  const typed = e.localName === 'textarea' || e.isContentEditable ||
    ['text', 'search', 'email', 'url', 'tel', 'password', 'number'].includes(type);
  return {typed, focused: active === e || (e.isContentEditable && e.contains(active))};
}"""


async def _click_to_focus(target: Any, timeout: Any, force: Any) -> None:
    info = await target.evaluate(_FILL_TARGET)
    if info['typed'] and not info['focused']:
        await target.click(timeout=timeout, force=force)


def _frame_fill_clicks_first(original: Any) -> Any:
    async def _fill(self: Any, selector: str, *args: Any, **kwargs: Any) -> None:
        if _launched_by_camoufox(self):
            target = self.locator(selector)
            if not kwargs.get('strict'):
                target = target.first
            await _click_to_focus(target, kwargs.get('timeout'), kwargs.get('force'))
        return await original(self, selector, *args, **kwargs)

    setattr(_fill, _MARK, True)
    _fill.__wrapped__ = original  # type: ignore[attr-defined]
    return _fill


def _handle_fill_clicks_first(original: Any) -> Any:
    async def fill(self: Any, *args: Any, **kwargs: Any) -> None:
        if _launched_by_camoufox(self):
            await _click_to_focus(self, kwargs.get('timeout'), kwargs.get('force'))
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
