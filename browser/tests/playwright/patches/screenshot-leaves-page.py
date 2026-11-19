"""
A screenshot changes nothing the page can see, and shows no caret.

Unless told caret="initial", Playwright hides the text caret for a screenshot
by setting `caret-color: transparent !important` in the style attribute of
every input, textarea and contenteditable element, from its utility world,
and putting the old value back afterwards. The page sees each change with a
MutationObserver, can read the transparent caret while the capture runs, and
every such element is left with a `style` attribute it did not have.

Firefox's capture (drawSnapshot) never paints the caret, so the launcher makes
"initial" the default: the image is the same and the page is left alone. The
guard checks both: no attribute changes, no `style` left behind, and every
capture with a focused, blinking caret byte-identical to one taken with
caret="hide".

    python browser/tests/playwright/patches/screenshot-leaves-page.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:0">
<input id="in" value="text" style="position:absolute;left:20px;top:20px;width:200px">
<textarea id="ta" style="position:absolute;left:20px;top:60px">area</textarea>
<div id="ce" contenteditable style="position:absolute;left:20px;top:120px;width:200px">editable</div>
<p><input id="bare"> <span id="bare-ce" contenteditable>unstyled</span></p>
<script>
  window.__seen = [];
  new MutationObserver((records) => {
    for (const r of records) window.__seen.push([r.type, r.target.id, r.attributeName]);
  }).observe(document.documentElement, {attributes: true, subtree: true, childList: true});
  (function watch() {
    const c = getComputedStyle(document.getElementById('in')).caretColor;
    if (c === 'transparent' || c === 'rgba(0, 0, 0, 0)') window.__seen.push(['caretColor', 'in', c]);
    requestAnimationFrame(watch);
  })();
</script></body></html>"""


def main() -> int:
    from camoufox.sync_api import Camoufox

    failures = []
    with Camoufox(executable_path=str(resolve_binary()), headless=True, os="linux") as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.focus("#in")
        shots = []
        for _ in range(6):
            shots.append(page.screenshot())
            page.wait_for_timeout(150)
        page.locator("#ta").screenshot()
        page.locator("#ce").screenshot()
        page.wait_for_timeout(200)
        page.add_script_tag(content="document.body.dataset.seen = JSON.stringify(window.__seen);"
                                    "document.body.dataset.styled = JSON.stringify("
                                    "['bare', 'bare-ce'].filter((id) => document.getElementById(id)"
                                    ".hasAttribute('style')));")
        seen = page.evaluate("document.body.dataset.seen")
        styled = page.evaluate("document.body.dataset.styled")
        # The reference, last: hiding the caret is what changes the page.
        hidden = page.screenshot(caret="hide")
    if seen != "[]":
        failures.append(f"the page saw the screenshot: {seen}")
    if styled != "[]":
        failures.append(f"elements left with a style attribute: {styled}")
    differing = [i for i, shot in enumerate(shots) if shot != hidden]
    if differing:
        failures.append(f"captures {differing} differ from the caret='hide' one: the capture painted a caret")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: screenshots leave the page alone and show no caret")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
