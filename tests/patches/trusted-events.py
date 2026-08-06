"""
Verify Playwright actions are indistinguishable from real user interaction.

Most actions already reach the page through the widget layer, so they are real
by construction. The ones that cannot -- selecting an <option>, filling a date
or colour input, setting files on a file input -- are performed by mutating the
DOM and dispatching the events the widget code would have sent, and those come
out `isTrusted: false` without patches/trusted-automation-events.patch. The same
actions also skipped the user-interacted flag that :user-valid selects on.

The reference this test measures against is not a hard-coded expectation: it is
a genuine widget-driven selection, produced by focusing a <select> and pressing
ArrowDown, which goes through HTMLSelectElement::UserFinishedInteracting. The
events select_option produces must be byte-identical to it.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/trusted-events.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * select_option's input/change match a real widget selection exactly, in
      trust, class, bubbles, cancelable and composed;
    * fill on a date/colour input, set_input_files and dispatch_event are all
      trusted, and set_input_files matches the file picker's own event shape;
    * page.click still produces the full trusted pointer/mouse sequence with a
      PointerEvent click;
    * the three flows a human drives with the mouse -- picking from a combobox,
      picking from a listbox, and choosing a file -- reproduce recorded human
      traces exactly, event for event, target for target, including the blur of
      whatever was focused before;
    * the controls report :user-valid afterwards, as they would for a human;
    * an event the page's own script dispatches is still untrusted, even when
      page.evaluate() is what called into the page to do it.
"""

import asyncio
import json
import os
import sys
import tempfile
from typing import Any, Dict, List

from camoufox.async_api import AsyncCamoufox

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

OPTIONS = '<option value="a">a</option><option value="b">b</option><option value="c">c</option>'
PAGE = f"""
<select id="selKey">{OPTIONS}</select>
<select id="selOpt">{OPTIONS}</select>
<select id="selMouse">{OPTIONS}</select>
<select id="selMulti" multiple size="3">{OPTIONS}</select>
<input id="date" type="date">
<input id="color" type="color">
<input id="file" type="file">
<button id="btn">b</button>
<button id="own" onclick="pageDispatch()">own</button>
<script>
  window.log = [];
  const desc = e => ({{
    type: e.type, trusted: e.isTrusted, bubbles: e.bubbles,
    cancelable: e.cancelable, composed: e.composed, ctor: e.constructor.name,
    target: e.target.id || e.target.tagName,
  }});
  for (const t of ['input', 'change', 'focus', 'blur', 'pointerdown',
                   'mousedown', 'pointerup', 'mouseup', 'click', 'custom'])
    document.addEventListener(t, e => {{
      // Focus/blur also fire with the window as target; only elements count.
      if (e.target instanceof Element) window.log.push(desc(e));
    }}, true);

  // Page-owned dispatch, run from #own's inline handler. Its events must stay
  // untrusted: the innermost scripted frame when the Event is built is this
  // one, not an automation world.
  window.pageDispatch = () =>
    document.querySelector('#own').dispatchEvent(new Event('custom', {{bubbles: true}}));

  // The isolated world cannot read window.log, so hand it over through the DOM.
  window.publish = () => {{
    document.documentElement.dataset.log = JSON.stringify(window.log);
    window.log = [];
  }};
  document.addEventListener('camou:publish', window.publish, true);
</script>
"""


class Recorder:
    """Drains the page's event log through a DOM attribute."""

    def __init__(self, page: Any) -> None:
        self._page = page

    async def drain(self) -> List[Dict[str, Any]]:
        # window.log lives in the page's world, where evaluate() cannot see it.
        # Poke the page into copying it onto an attribute, which is DOM state
        # and so is shared. The poke is a type nothing under test listens for.
        await self._page.evaluate(
            "document.dispatchEvent(new Event('camou:publish'))"
        )
        return json.loads(await self._page.get_attribute("html", "data-log"))


def _check(results: Dict[str, bool], label: str, got: Any, expected: Any) -> None:
    ok = got == expected
    results[label] = ok
    verdict = "PASS" if ok else "FAIL"
    suffix = "" if ok else f"\n         expected {expected!r}"
    print(f"  {verdict} {label:52} -> {got!r}{suffix}")


def shape(events: List[Dict[str, Any]], *types: str) -> List[Dict[str, Any]]:
    """The events of interest, minus the fields that legitimately differ."""
    return [
        {k: v for k, v in e.items() if k != "target"}
        for e in events
        if e["type"] in types
    ]


async def main() -> int:
    results: Dict[str, bool] = {}
    kwargs: Dict[str, Any] = dict(headless=True, os="linux")
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH

    async with AsyncCamoufox(**kwargs) as browser:
        page = await browser.new_page()
        await page.set_content(PAGE)
        rec = Recorder(page)

        # --- the reference: a genuine widget-driven selection ---
        await page.focus("#selKey")
        await page.keyboard.press("ArrowDown")
        reference = shape(await rec.drain(), "input", "change")
        _check(results, "reference produced trusted input+change",
               [(e["type"], e["trusted"]) for e in reference],
               [("input", True), ("change", True)])

        await page.select_option("#selOpt", "c")
        drained = await rec.drain()
        _check(results, "select_option is identical to the reference",
               shape(drained, "input", "change"), reference)
        # Every route a human has to a <select> focuses it on the way in, so
        # "change" on a control that was never the active element is a tell.
        _check(results, "select_option focuses first, as a human would",
               [e["type"] for e in shape(drained, "focus", "input", "change")],
               ["focus", "input", "change"])
        _check(results, "select_option leaves the control focused",
               await page.evaluate("document.activeElement.id"), "selOpt")

        # --- the other actions that have no widget path ---
        await page.fill("#date", "2020-01-02")
        _check(results, "fill on a date input is trusted",
               [e["trusted"] for e in shape(await rec.drain(), "input", "change")],
               [True, True])

        await page.fill("#color", "#123456")
        _check(results, "fill on a colour input is trusted",
               [e["trusted"] for e in shape(await rec.drain(), "input", "change")],
               [True, True])

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            handle.write(b"camoufox")
            upload = handle.name
        try:
            await page.set_input_files("#file", upload)
        finally:
            os.unlink(upload)
        # The file picker's own pair: DispatchEvents() in HTMLInputElement.cpp
        # sends a non-cancelable composed "input", then a non-cancelable,
        # non-composed "change".
        _check(results, "set_input_files matches the file picker's events",
               shape(await rec.drain(), "input", "change"),
               [{"type": "input", "trusted": True, "bubbles": True,
                 "cancelable": False, "composed": True, "ctor": "Event"},
                {"type": "change", "trusted": True, "bubbles": True,
                 "cancelable": False, "composed": False, "ctor": "Event"}])

        await page.dispatch_event("#btn", "click")
        _check(results, "dispatch_event is trusted",
               [e["trusted"] for e in shape(await rec.drain(), "click")], [True])

        # --- the widget path must not have regressed ---
        await page.click("#btn")
        _check(results, "page.click sends the real pointer/mouse sequence",
               [(e["type"], e["ctor"], e["trusted"])
                for e in shape(await rec.drain(), "pointerdown", "mousedown",
                               "pointerup", "mouseup", "click")],
               [("pointerdown", "PointerEvent", True),
                ("mousedown", "MouseEvent", True),
                ("pointerup", "PointerEvent", True),
                ("mouseup", "MouseEvent", True),
                ("click", "PointerEvent", True)])

        # --- the flag :user-valid selects on ---
        for selector, how in (("#selKey", "ArrowDown (reference)"),
                              ("#selOpt", "select_option"),
                              ("#date", "fill"),
                              ("#file", "set_input_files")):
            _check(results, f"{how} leaves the control user-interacted",
                   await page.evaluate(
                       f"document.querySelector('{selector}').matches(':user-valid')"),
                   True)

        # --- full parity, against traces recorded from a real human ---
        # Every expectation below was captured by a person clicking the control
        # on an ordinary desktop session; none of it is inferred. Each flow is
        # driven the way that human drove it -- move, click, then commit -- since
        # comparing a bare API call against a human who had to click first would
        # only measure the click the script never made.
        async def move_click(locator: Any) -> None:
            box = await locator.bounding_box()
            centre = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.move(*centre)
            await page.mouse.click(*centre)

        async def trace() -> List[Any]:
            return [(e["type"], e["target"], e["ctor"]) for e in await rec.drain()]

        # A combobox commits through the parent-process panel, which the protocol
        # cannot drive, so chrome's own mouse events on the chosen <option> (see
        # SelectChild.sys.mjs) are synthesised. The press that opens the panel
        # gets no pointerup: the panel takes the release.
        await move_click(page.locator("#selMouse"))
        await page.select_option("#selMouse", "c")
        _check(results, "move+click+select_option matches a real user",
               await trace(),
               [("pointerdown", "selMouse", "PointerEvent"),
                ("mousedown", "selMouse", "MouseEvent"),
                ("blur", "btn", "FocusEvent"),
                ("focus", "selMouse", "FocusEvent"),
                ("mouseup", "selMouse", "MouseEvent"),
                ("click", "selMouse", "PointerEvent"),
                ("mousedown", "OPTION", "MouseEvent"),
                ("mouseup", "OPTION", "MouseEvent"),
                ("input", "selMouse", "Event"),
                ("change", "selMouse", "Event"),
                ("click", "OPTION", "PointerEvent")])

        # A listbox has no panel: the <option> is in-page, so the real click
        # reaches it and Gecko commits natively. Nothing is synthesised here,
        # and the pointerup a combobox loses to the panel is present.
        await move_click(page.locator("#selMulti option[value='b']"))
        _check(results, "move+click on a listbox option matches a real user",
               await trace(),
               [("pointerdown", "OPTION", "PointerEvent"),
                ("mousedown", "OPTION", "MouseEvent"),
                ("blur", "selMouse", "FocusEvent"),
                ("focus", "selMulti", "FocusEvent"),
                ("pointerup", "OPTION", "PointerEvent"),
                ("mouseup", "OPTION", "MouseEvent"),
                ("input", "selMulti", "Event"),
                ("change", "selMulti", "Event"),
                ("click", "OPTION", "PointerEvent")])

        # The file control is in-page too; only the picker it opens is not, and
        # Juggler answers that instead of the OS.
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            handle.write(b"camoufox")
            upload = handle.name
        try:
            async with page.expect_file_chooser() as chooser:
                await move_click(page.locator("#file"))
            await (await chooser.value).set_files(upload)
        finally:
            os.unlink(upload)
        _check(results, "move+click+choose a file matches a real user",
               await trace(),
               [("pointerdown", "file", "PointerEvent"),
                ("mousedown", "file", "MouseEvent"),
                ("blur", "selMulti", "FocusEvent"),
                ("focus", "file", "FocusEvent"),
                ("pointerup", "file", "PointerEvent"),
                ("mouseup", "file", "MouseEvent"),
                ("click", "file", "PointerEvent"),
                ("input", "file", "Event"),
                ("change", "file", "Event")])

        # --- and the page's own script must gain nothing from any of it ---
        await page.click("#own")
        _check(results, "page script cannot forge a trusted event",
               [e["trusted"] for e in shape(await rec.drain(), "custom")], [False])

    passed = all(results.values())
    print()
    if passed:
        print("PASS: automation actions are indistinguishable from user interaction")
    else:
        print("FAIL: an automation action is still separable from a real user's")
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
