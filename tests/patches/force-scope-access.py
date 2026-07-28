"""
Verify `forceScopeAccess` reaches closed shadow roots without relocating the
main world (daijro/camoufox#628).

patches/shadow-root-bypass.patch adds `Element.shadowRootUnl` to the WebIDL,
gated on Func="Document::IsCallerChromeOrAddon". page.evaluate() runs as the
page principal, so that gate never passed and the property read as `undefined`.
Meanwhile `forceScopeAccess` was declared in settings/properties.json and
settings/camoucfg.jvv but nothing in additions/juggler/ ever consulted it, so
the flag was accepted, validated, and silently ignored.

FrameTree.js now installs a getter whose body stays in the juggler module's
system-principal scope, so the WebIDL gate is satisfied by the *caller* while
the default execution context remains the real page window.

That last part is the point of this test. The obvious alternative -- evaluating
in a Cu.Sandbox over the page window -- also unlocks the binding, but Xray
vision then hides page expandos, so `page.evaluate('window.pageSecret')`
silently starts returning None for anyone who enables the flag. These cases pin
both halves: the binding works AND main-world semantics are untouched.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/force-scope-access.py
(without the env var it uses the camoufox-managed browser download.)

Point this at a PACKAGED build (`make package-linux`), not at
camoufox-*/obj-*/dist/bin/camoufox-bin. Like the other scripts in this
directory it launches through AsyncCamoufox, and that path sets FONTCONFIG_FILE
from the installed bundle and expects the packaged fonts/ tree. An unpackaged
`make build` tree has neither, so font init fails ("[GFX1]: no fonts"), pending
idle-startup work becomes a quit-application shutdown blocker, and Playwright
force-kills the browser after its graceful-close timeout -- surfacing as a
confusing TargetClosedError on a later new_page(). Measured 5/5 failures
unpackaged vs 0/5 packaged for the same commit. (`make tests` is unaffected: its
conftest launches via plain Playwright, not AsyncCamoufox.)

What PASS means:
    * with forceScopeAccess=True, page.evaluate() can read a closed shadow root
      through `element.shadowRootUnl` and query inside it;
    * with the flag off (the default), `shadowRootUnl` is undefined -- the
      accessor is not installed and the default build gains no new surface;
    * in BOTH modes page.evaluate() still sees page globals and page expandos,
      element handles still resolve, and ChromeUtils is not exposed to the page.
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
  // Page-owned state that main-world evaluation must keep seeing.
  window.pageSecret = 41;
  document.querySelector('#target').pageMarker = 'page-owned';
  document.documentElement.dataset.chromeUtilsType = typeof ChromeUtils;
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
    print(f"  {verdict} {label:38} -> {got!r}{suffix}")


async def _run(force_scope_access: bool) -> bool:
    results: Dict[str, Any] = {}
    print(f"\n=== forceScopeAccess={force_scope_access} ===")
    async with AsyncCamoufox(**_launch_kwargs(force_scope_access)) as browser:
        page = await browser.new_page()
        await page.set_content(PAGE)

        # --- the feature itself ---
        shadow_type = await page.evaluate(
            "typeof document.querySelector('#host').shadowRootUnl"
        )
        _check(
            results,
            "typeof element.shadowRootUnl",
            shadow_type,
            "object" if force_scope_access else "undefined",
        )

        if force_scope_access:
            text = await page.evaluate(
                "document.querySelector('#host').shadowRootUnl"
                ".querySelector('#secret').textContent"
            )
            _check(results, "closed shadow root is queryable", text, "inside")
            # The plain, spec-compliant accessor must still refuse.
            _check(
                results,
                "spec .shadowRoot still null for closed",
                await page.evaluate("document.querySelector('#host').shadowRoot"),
                None,
            )

        # --- main-world semantics must be identical in both modes ---
        _check(results, "page global visible to evaluate", await page.evaluate("window.pageSecret"), 41)
        _check(
            results,
            "page expando visible to evaluate",
            await page.evaluate("document.querySelector('#target').pageMarker"),
            "page-owned",
        )

        handle = await page.evaluate_handle("() => ({value: 42})")
        _check(results, "evaluate_handle round-trips", await handle.json_value(), {"value": 42})
        await handle.dispose()

        element = await page.query_selector("#target")
        _check(
            results,
            "element handle resolves",
            await element.get_attribute("id") if element else None,
            "target",
        )

        # --- the page must not gain chrome privileges either way ---
        _check(
            results,
            "page cannot see ChromeUtils",
            await page.get_attribute("html", "data-chrome-utils-type"),
            "undefined",
        )
        _check(
            results,
            "evaluate cannot see ChromeUtils",
            await page.evaluate("typeof ChromeUtils"),
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
        print("PASS: forceScopeAccess unlocks closed shadow roots and main-world "
              "evaluation is unchanged")
    else:
        print("FAIL: forceScopeAccess is ignored, or it altered main-world evaluation")
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
