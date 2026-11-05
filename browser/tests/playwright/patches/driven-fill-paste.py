"""
fill() and keyboard.insert_text() reach the page as a person's paste.

Playwright fills a text field with Page.insertText. Typing a whole string key
by key takes a quarter of a second per character, and Juggler's old insert
(one beforeinput/input pair, no key events, no paste) is nothing a person can
do. A person enters a whole string by pasting it: the paste shortcut goes down,
Firefox's paste fires a trusted `paste` whose clipboardData holds the text,
then `beforeinput` and `input` (insertFromPaste), and the shortcut comes up.
Juggler runs Firefox's own paste with the text, so every field of those events
is Firefox's; the system clipboard is not used.

A person clicks the field before pasting into it, so fill() clicks a text
field that does not have focus (the launcher, camoufox/driver_defaults.py).
A field that has focus is pasted into as it is. A page that cancels the paste
makes fill() fail, as the paste fails for a person.

    python browser/tests/playwright/patches/driven-fill-paste.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

TEXT = "Hi there, 42!é嗨"
PAGE = ('<!doctype html><html><body><input id="fill" style="width:201px">'
        '<input id="blocked" style="width:201px"></body></html>')
RECORD = """() => {
  window.__events = [];
  const clip = (e) => e.clipboardData ? [e.clipboardData.types.join(','), e.clipboardData.getData('text/plain')] : null;
  for (const id of ['fill', 'blocked']) {
    const el = document.getElementById(id);
    for (const t of ['keydown', 'keypress', 'keyup', 'paste', 'beforeinput', 'input',
                     'mousedown', 'focus', 'mouseup', 'click']) {
      el.addEventListener(t, (e) => {
        const r = [id, t, e.isTrusted];
        if (e instanceof KeyboardEvent) r.push(e.key, e.code, e.ctrlKey, e.metaKey);
        if (t === 'paste') r.push(clip(e));
        if (t === 'beforeinput' || t === 'input') r.push(e.inputType);
        window.__events.push(r);
      });
    }
  }
  document.getElementById('blocked').addEventListener('paste', (e) => e.preventDefault());
}"""


def probe(binary):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=True, os="linux") as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.evaluate(RECORD)
        page.locator("#fill").fill(TEXT)
        first = page.evaluate("window.__events"), page.locator("#fill").input_value()
        page.evaluate("window.__events = []")
        page.locator("#fill").fill("ok")
        again = page.evaluate("window.__events")
        try:
            page.locator("#blocked").fill("no", timeout=5000)
            blocked = None
        except Exception as e:  # noqa: BLE001 - the failure is what is checked
            blocked = str(e)
        return first, again, blocked, page.locator("#blocked").input_value()


def main() -> int:
    (events, value), again, blocked, blocked_value = probe(resolve_binary())
    failures = []
    if value != TEXT:
        failures.append(f"the field holds {value!r}")
    if [t for _, t, *_ in again if t in ("mousedown", "focus", "click")]:
        failures.append(f"filling the focused field clicked it again: {again}")
    # After the click that focuses the field: the paste, and nothing typed.
    stream = [e for e in events if e[1] not in ("mousedown", "focus", "mouseup", "click")]
    want = [
        ["fill", "keydown", True, "Control", "ControlLeft", True, False],
        ["fill", "keydown", True, "v", "KeyV", True, False],
        ["fill", "paste", True, ["text/plain", TEXT]],
        ["fill", "beforeinput", True, "insertFromPaste"],
        ["fill", "input", True, "insertFromPaste"],
        ["fill", "keyup", True, "v", "KeyV", True, False],
        ["fill", "keyup", True, "Control", "ControlLeft", False, False],
    ]
    if stream != want:
        failures.append(f"fill's events {stream}, want a paste: {want}")
    if not blocked or "cancelled the paste" not in blocked or blocked_value:
        failures.append(f"a page that cancels the paste: fill raised {blocked!r}, field holds {blocked_value!r}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: fill pastes as a person does")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
