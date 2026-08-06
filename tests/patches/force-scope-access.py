"""
Verify `forceScopeAccess` reaches closed shadow roots (daijro/camoufox#628).

patches/shadow-root-bypass.patch adds `Element.shadowRootUnl` to the WebIDL,
gated on Func="Document::IsCallerChromeOrAddon". That gate tests the *caller*,
so whether page.evaluate() can read the property depends entirely on the
principal of the world it runs in.

With `forceScopeAccess` set, FrameTree.js builds the default execution context
as a system-principal Cu.Sandbox in its own compartment -- the "master sandbox"
-- instead of the page-principal sandbox used otherwise. The gate then passes.
The flag had been declared in settings/properties.json and settings/camoucfg.jvv
with nothing consulting it, so it was accepted, validated, and ignored (#628).

Note what this costs, and why the flag is opt-in and off by default: evaluated
scripts run with chrome privileges while it is on. That is the point of the
flag, but it means anything you evaluate can reach far past the page.

What it does *not* cost: page-visible surface. The accessor lives in the
sandbox, never on the page's own Element.prototype, so a detection script cannot
find `shadowRootUnl` and cannot tell the flag is set.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/force-scope-access.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * with forceScopeAccess=True, page.evaluate() can read a closed shadow root
      through `element.shadowRootUnl` and query inside it, and runs privileged;
    * with the flag off (the default), `shadowRootUnl` is undefined and
      evaluation has no privileges;
    * in BOTH modes the page sees no trace of the property, evaluation stays
      isolated from page JS state, element handles still resolve, and the world
      does not carry state across a navigation.
"""

import asyncio
import os
import sys
from typing import Any, Dict

from camoufox.async_api import AsyncCamoufox

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

PAGE = """
<div id="host"></div>
<main id="target">content</main>
<script>
  const host = document.querySelector('#host');
  const root = host.attachShadow({mode: 'closed'});
  root.innerHTML = '<span id="secret">inside</span>';
  // Page-owned state; isolated evaluation must not see it.
  window.pageSecret = 41;
  document.querySelector('#target').pageMarker = 'page-owned';
  // What the page itself can detect.
  const data = document.documentElement.dataset;
  data.chromeUtilsType = typeof ChromeUtils;
  data.shadowUnlOnElement = typeof host.shadowRootUnl;
  data.shadowUnlOnPrototype = ('shadowRootUnl' in Element.prototype) ? 'present' : 'absent';
</script>
"""


def _launch_kwargs(force_scope_access: bool) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(headless=True, os="linux")
    if force_scope_access:
        # Not a documented Camoufox() kwarg; pass it straight through as config.
        kwargs["config"] = {"forceScopeAccess": True}
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


def _check(results: Dict[str, Any], label: str, got: Any, expected: Any) -> None:
    ok = got == expected
    results[label] = ok
    verdict = "PASS" if ok else "FAIL"
    suffix = "" if ok else f" (expected {expected!r})"
    print(f"  {verdict} {label:40} -> {got!r}{suffix}")


async def _run(force_scope_access: bool) -> bool:
    results: Dict[str, Any] = {}
    print(f"\n=== forceScopeAccess={force_scope_access} ===")
    async with AsyncCamoufox(**_launch_kwargs(force_scope_access)) as browser:
        page = await browser.new_page()
        await page.set_content(PAGE)

        # --- the feature itself ---
        _check(
            results,
            "typeof element.shadowRootUnl",
            await page.evaluate("typeof document.querySelector('#host').shadowRootUnl"),
            "object" if force_scope_access else "undefined",
        )

        if force_scope_access:
            _check(
                results,
                "closed shadow root is queryable",
                await page.evaluate(
                    "document.querySelector('#host').shadowRootUnl"
                    ".querySelector('#secret').textContent"
                ),
                "inside",
            )
            # The plain, spec-compliant accessor must still refuse.
            _check(
                results,
                "spec .shadowRoot still null for closed",
                await page.evaluate("document.querySelector('#host').shadowRoot"),
                None,
            )

        # --- the privilege that comes with it ---
        _check(
            results,
            "evaluation is privileged",
            await page.evaluate("typeof ChromeUtils"),
            "object" if force_scope_access else "undefined",
        )

        # --- the page must learn nothing, either way ---
        _check(results, "page cannot see ChromeUtils", await page.get_attribute("html", "data-chrome-utils-type"), "undefined")
        _check(results, "page cannot see shadowRootUnl", await page.get_attribute("html", "data-shadow-unl-on-element"), "undefined")
        _check(
            results,
            "page prototype is untouched",
            await page.get_attribute("html", "data-shadow-unl-on-prototype"),
            "absent",
        )

        # --- isolation is unchanged by the flag ---
        _check(results, "page global hidden from evaluate", await page.evaluate("window.pageSecret"), None)
        _check(
            results,
            "page expando hidden from evaluate",
            await page.evaluate("document.querySelector('#target').pageMarker"),
            None,
        )
        _check(results, "DOM still reachable", await page.evaluate("document.querySelector('#target').textContent"), "content")

        element = await page.query_selector("#target")
        _check(
            results,
            "element handle resolves",
            await element.get_attribute("id") if element else None,
            "target",
        )
        handle = await page.evaluate_handle("() => ({value: 42})")
        _check(results, "evaluate_handle round-trips", await handle.json_value(), {"value": 42})
        await handle.dispose()

        # --- the world must not outlive its document ---
        # The master sandbox is the only world that is cached, so it is the only
        # one that could carry evaluate() state from one page to the next.
        await page.evaluate("globalThis.leakedAcrossNavigation = 'yes'")
        await page.goto("about:blank")
        _check(
            results,
            "world is fresh after navigation",
            await page.evaluate("typeof globalThis.leakedAcrossNavigation"),
            "undefined",
        )

    return all(results.values())


async def main() -> int:
    passed = True
    for force_scope_access in (False, True):
        if not await _run(force_scope_access):
            passed = False

    print()
    if passed:
        print("PASS: forceScopeAccess unlocks closed shadow roots without leaking to the page")
    else:
        print("FAIL: forceScopeAccess is ignored, or it changed what the page can see")
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
