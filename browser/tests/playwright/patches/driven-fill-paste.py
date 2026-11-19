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
A field that has focus is pasted into as it is. A field in a frame gets the
same paste: the system clipboard must not reach it, whatever it holds.

A page that cancels the paste decides what happens to it. One that inserts the
text itself has filled the field; one that refuses it gets the text typed, key
by key, as a person types what a page will not let them paste, and stops if
the focus leaves the field. A read-only field takes nothing, without error. A
field another
element covers is filled without a click, since a person could not click it. A
page sharing its process with another gets its own text.

    python browser/tests/playwright/patches/driven-fill-paste.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402
from playwright.sync_api import Error as PlaywrightError  # noqa: E402

TEXT = "Hi there, 42!é嗨"
PAGE = ('<!doctype html><html><body><input id="fill" style="width:201px">'
        '<input id="blocked" style="width:201px">'
        '<input id="keydown-blocked" style="width:201px">'
        '<div id="handled" contenteditable style="width:201px;height:20px"></div>'
        '<div style="position:relative;width:201px;height:20px"><input id="covered" style="width:201px">'
        '<div style="position:absolute;inset:0;background:#fff"></div></div>'
        '<input id="handle" style="width:201px">'
        '<ul><li id="item" contenteditable style="width:201px"></li></ul>'
        '<input id="readonly" readonly value="kept" style="width:201px">'
        '<input id="leaves" style="width:201px"><input id="next" style="width:201px">'
        '<iframe id="plain" srcdoc="<!doctype html><input id=inner>"></iframe>'
        '<iframe name="design" srcdoc="<!doctype html><body style=height:40px>"></iframe></body></html>')
RECORD = """() => {
  window.__events = [];
  const clip = (e) => e.clipboardData ? [e.clipboardData.types.join(','), e.clipboardData.getData('text/plain')] : null;
  for (const id of ['fill', 'blocked', 'keydown-blocked', 'handled', 'covered', 'handle']) {
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
  document.getElementById('keydown-blocked').addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'v') e.preventDefault();
  });
  document.getElementById('handled').addEventListener('paste', (e) => {
    e.preventDefault();
    document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
  });
  const leaves = document.getElementById('leaves');
  leaves.addEventListener('paste', (e) => e.preventDefault());
  leaves.addEventListener('input', () => document.getElementById('next').focus());
}"""
TYPED = "Ab 1é"


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
        out = {"first": first, "again": again}
        page.evaluate("window.__events = []")
        page.locator("#blocked").fill(TYPED, timeout=5000)
        out["blocked"] = page.locator("#blocked").input_value(), page.evaluate("window.__events")
        page.locator("#keydown-blocked").fill("ok", timeout=5000)
        out["keydown_blocked"] = page.locator("#keydown-blocked").input_value()
        page.locator("#handled").fill(TEXT, timeout=5000)
        out["handled"] = page.locator("#handled").text_content()
        page.evaluate("window.__events = []")
        page.locator("#covered").fill(TEXT, timeout=5000)
        out["covered"] = page.locator("#covered").input_value(), page.evaluate("window.__events")
        page.evaluate("window.__events = []")
        page.locator("#handle").element_handle().fill(TEXT, timeout=5000)
        out["handle"] = page.locator("#handle").input_value(), page.evaluate("window.__events")
        inner = page.frame_locator("#plain").locator("#inner")
        inner.fill(TEXT, timeout=5000)
        out["inner"] = inner.input_value()
        page.locator("#item").fill("ok", timeout=5000)
        out["item"] = page.locator("#item").text_content()
        page.locator("#readonly").focus()
        page.keyboard.insert_text("no")
        out["readonly"] = page.locator("#readonly").input_value()
        page.locator("#leaves").focus()
        try:
            page.keyboard.insert_text("abcd")
            out["left"] = None
        except PlaywrightError as e:
            out["left"] = str(e), page.locator("#leaves").input_value(), page.locator("#next").input_value()
        design = page.frame(name="design")
        design.evaluate("document.designMode = 'on'")
        design.locator("body").click()
        page.keyboard.insert_text("ok")
        out["design"] = design.locator("body").text_content()
    return out


def probe_mac(binary):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=True, os="macos") as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.evaluate(RECORD)
        page.locator("#fill").fill(TEXT)
        return page.locator("#fill").input_value(), page.evaluate("window.__events")


def probe_shared_process(binary):
    from camoufox.sync_api import Camoufox

    prefs = {"dom.ipc.processCount": 1, "dom.ipc.processCount.webIsolated": 1}
    with Camoufox(executable_path=str(binary), headless=True, os="linux", firefox_user_prefs=prefs) as browser:
        context = browser.new_context()
        pages = [context.new_page(), context.new_page()]
        for page in pages:
            page.set_content('<!doctype html><input id="x">')
        pages[1].locator("#x").focus()
        pages[1].bring_to_front()
        pages[0].locator("#x").fill("one", timeout=5000)
        return pages[0].locator("#x").input_value(), pages[1].locator("#x").input_value()


def main() -> int:
    binary = resolve_binary()
    out = probe(binary)
    events, value = out["first"]
    again = out["again"]
    failures = []
    if out["inner"] != TEXT:
        failures.append(f"the field in a frame holds {out['inner']!r}")
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

    typed_value, typed_events = out["blocked"]
    if typed_value != TYPED:
        failures.append(f"a page that refuses the paste: the field holds {typed_value!r}, want {TYPED!r}")
    keys = [e[3:5] for e in typed_events if e[1] == "keydown" and e[3] not in ("Control", "v", "Shift")]
    if keys[:4] != [["A", "KeyA"], ["b", "KeyB"], [" ", "Space"], ["1", "Digit1"]]:
        failures.append(f"a page that refuses the paste: typed keys {keys}")
    if not [e for e in typed_events if e[1] == "input" and e[3] == "insertText"]:
        failures.append(f"a page that refuses the paste: no typed input in {typed_events}")
    if out["keydown_blocked"] != "ok":
        failures.append(f"a page that cancels the shortcut: the field holds {out['keydown_blocked']!r}")
    if out["handled"] != TEXT:
        failures.append(f"a page that inserts the paste itself: the field holds {out['handled']!r}")

    if out["item"] != "ok":
        failures.append(f"a list item: a contenteditable with a numeric value holds {out['item']!r}")
    if out["readonly"] != "kept":
        failures.append(f"a read-only field holds {out['readonly']!r}")
    # One key lands in the field, and its input event moves the focus.
    if not out["left"] or "lost focus" not in out["left"][0] or out["left"][1:] != ("a", ""):
        failures.append(f"typing that loses the focus went on, or did not say so: {out['left']}")
    if out["design"] != "ok":
        failures.append(f"a designMode frame holds {out['design']!r}")

    covered_value, covered_events = out["covered"]
    if covered_value != TEXT:
        failures.append(f"a covered field holds {covered_value!r}")
    if [e for e in covered_events if e[1] in ("mousedown", "click")]:
        failures.append(f"a covered field got a click: {covered_events}")

    handle_value, handle_events = out["handle"]
    if handle_value != TEXT:
        failures.append(f"ElementHandle.fill: the field holds {handle_value!r}")
    if handle_events[:1] != [["handle", "mousedown", True]]:
        failures.append(f"ElementHandle.fill did not click first: {handle_events[:3]}")

    mac_value, mac_events = probe_mac(binary)
    mac_keys = [e[3:7] for e in mac_events if e[1] == "keydown"]
    if mac_value != TEXT or mac_keys != [["Meta", "MetaLeft", False, True], ["v", "KeyV", False, True]]:
        failures.append(f"macOS identity: field {mac_value!r}, keys {mac_keys}")

    one, other = probe_shared_process(binary)
    if (one, other) != ("one", ""):
        failures.append(f"two pages in one process: the filled page holds {one!r}, the other {other!r}")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: fill pastes as a person does")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
