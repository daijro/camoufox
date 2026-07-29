"""
Verify page.evaluate() runs in an isolated world, not the page's own global.

This is Camoufox's core automation-stealth property: Playwright routes
page.evaluate() to the execution context juggler names '' (ffPage.js maps that
name to its "main" world), and FrameTree.js gives that name a Cu.Sandbox with
its own compartment instead of the page window. Everything the automation
evaluates therefore happens somewhere page script cannot reach, read, or hook.

It regressed once already: commit 03c1230 ("migrate Juggler modules from JSM to
ESM") replaced the juggler sources with upstream Playwright's, and upstream puts
that context on the page window itself. The flip is a two-line change, invisible
in a diff full of module-format churn, and no test noticed -- page.evaluate()
keeps working either way, it just stops being hidden.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/isolated-evaluate.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * page state -- globals, element expandos -- is NOT visible to evaluate();
    * state written by evaluate() is NOT visible to page script;
    * page-installed traps on Function.prototype.toString, window.eval and
      Object.defineProperty never fire while the automation works;
    * evaluate() gets no chrome privileges by default;
    * and none of that breaks Playwright: locators, handles, clicks, and
      element evaluation all still work.
"""

import asyncio
import os
import sys
from typing import Any, Dict

from camoufox.async_api import AsyncCamoufox

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

PAGE = """
<main id="target">content</main>
<button id="probe">probe</button>
<script>
  // Page-owned state. None of it should be reachable from page.evaluate().
  window.pageSecret = 41;
  document.querySelector('#target').pageMarker = 'page-owned';

  // Traps a detection script would install to catch automation evaluating in
  // the page's world. Each must stay at zero.
  window.toStringCalls = 0;
  const realToString = Function.prototype.toString;
  Function.prototype.toString = function () {
    window.toStringCalls++;
    return realToString.call(this);
  };
  window.evalCalls = 0;
  const realEval = window.eval;
  window.eval = function (...args) {
    window.evalCalls++;
    return realEval.apply(this, args);
  };
  window.definePropertyCalls = 0;
  const realDefineProperty = Object.defineProperty;
  Object.defineProperty = function (...args) {
    window.definePropertyCalls++;
    return realDefineProperty.apply(this, args);
  };

  // The page's own report, triggered by a real click so that it runs as page
  // script -- reading it back through evaluate() would prove nothing.
  document.querySelector('#probe').addEventListener('click', () => {
    const data = document.documentElement.dataset;
    data.sawAutomationExpando = typeof window.automationMark;
    data.sawAutomationGlobal = typeof window.automationGlobal;
    data.toStringCalls = String(window.toStringCalls);
    data.evalCalls = String(window.evalCalls);
    data.definePropertyCalls = String(window.definePropertyCalls);
  });
</script>
"""


def _launch_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(headless=True, os="linux")
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


def _check(results: Dict[str, Any], label: str, got: Any, expected: Any) -> None:
    ok = got == expected
    results[label] = ok
    verdict = "PASS" if ok else "FAIL"
    suffix = "" if ok else f" (expected {expected!r})"
    print(f"  {verdict} {label:42} -> {got!r}{suffix}")


async def _run() -> bool:
    results: Dict[str, Any] = {}
    async with AsyncCamoufox(**_launch_kwargs()) as browser:
        page = await browser.new_page()
        await page.set_content(PAGE)

        print("\n=== page state is invisible to evaluate() ===")
        _check(results, "page global", await page.evaluate("window.pageSecret"), None)
        _check(
            results,
            "page expando on element",
            await page.evaluate("document.querySelector('#target').pageMarker"),
            None,
        )
        # The DOM itself is still fully reachable -- isolation hides page *JS*
        # state, not the document.
        _check(results, "DOM still reachable", await page.evaluate("document.querySelector('#target').textContent"), "content")

        print("\n=== evaluate() state is invisible to the page ===")
        await page.evaluate("window.automationMark = 'automation'")
        await page.evaluate("globalThis.automationGlobal = 'automation'")
        # Readable from the automation's own world...
        _check(results, "automation can read its own write", await page.evaluate("window.automationMark"), "automation")
        _check(results, "automation global persists", await page.evaluate("globalThis.automationGlobal"), "automation")

        # ...and exercise the ordinary automation surface before asking the page
        # what it noticed.
        await page.wait_for_selector("#target")
        await page.locator("#target").evaluate("el => el.tagName")
        await page.inner_text("#target")
        handle = await page.query_selector("#target")
        assert handle is not None
        await handle.get_attribute("id")

        await page.click("#probe")
        data = {
            key: await page.get_attribute("html", attr)
            for key, attr in (
                ("expando", "data-saw-automation-expando"),
                ("global", "data-saw-automation-global"),
                ("toString", "data-to-string-calls"),
                ("eval", "data-eval-calls"),
                ("defineProperty", "data-define-property-calls"),
            )
        }
        _check(results, "page cannot see evaluate's window write", data["expando"], "undefined")
        _check(results, "page cannot see evaluate's global", data["global"], "undefined")

        print("\n=== page traps never fire ===")
        _check(results, "Function.prototype.toString untouched", data["toString"], "0")
        _check(results, "window.eval untouched", data["eval"], "0")
        _check(results, "Object.defineProperty untouched", data["defineProperty"], "0")

        print("\n=== no privileges, and Playwright still works ===")
        _check(results, "evaluate cannot see ChromeUtils", await page.evaluate("typeof ChromeUtils"), "undefined")
        _check(results, "locator text", await page.locator("#target").text_content(), "content")
        _check(results, "locator evaluate", await page.locator("#target").evaluate("el => el.id"), "target")
        _check(results, "element handle attribute", await handle.get_attribute("id"), "target")
        value_handle = await page.evaluate_handle("() => ({value: 42})")
        _check(results, "evaluate_handle round-trips", await value_handle.json_value(), {"value": 42})
        await value_handle.dispose()
        _check(results, "evaluate with argument", await page.evaluate("(x) => x * 2", 21), 42)

    return all(results.values())


async def main() -> int:
    passed = await _run()
    print()
    if passed:
        print("PASS: page.evaluate() is isolated from the page")
        return 0
    print("FAIL: page.evaluate() is reaching the page's own world")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
