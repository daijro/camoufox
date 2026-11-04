"""Screenshots that leave the page alone.

Playwright hides the text caret for a screenshot unless told caret="initial":
from its utility world it sets `caret-color: transparent !important` in the
style attribute of every input, textarea and contenteditable element, then puts
the old value back. A page sees each change with a MutationObserver, reads the
transparent caret while the capture runs, and is left with a `style` attribute
on elements that had none (docs/input-dispatch.md, "Screenshots").

Firefox's capture (drawSnapshot) never paints the caret, so hiding it changes
nothing in the image. A screenshot of a page Camoufox launched defaults to
caret="initial"; a caller who passes caret= still gets what they ask for.
"""

from typing import Any

_MARK = '_camoufox_screenshots'


def mark(target: Any) -> Any:
    """Make screenshots of every page under `target` (a Browser or
    BrowserContext from a Camoufox launch) default to caret="initial"."""
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


def _install() -> None:
    # Locator.screenshot goes through ElementHandle.screenshot.
    from playwright._impl._element_handle import ElementHandle
    from playwright._impl._page import Page

    for cls in (Page, ElementHandle):
        if not getattr(cls.screenshot, _MARK, False):
            cls.screenshot = _with_caret_default(cls.screenshot)
