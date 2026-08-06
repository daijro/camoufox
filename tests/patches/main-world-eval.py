"""
Verify the `mw:` main-world escape hatch (daijro/camoufox#631).

page.evaluate() runs in an isolated world (tests/patches/isolated-evaluate.py),
so the page's own JS state is invisible to it. `main_world_eval=True` plus a
"mw:" prefix opts a single evaluation into the page's real global instead:

    page.evaluate("mw:window.someVariableThePageDefined")

Runtime.callFunction() spots the prefix on the expression Playwright forwards to
its utility script and replays the call against the page's global, through a
standalone equivalent of utilityScript.evaluate compiled there.

Two things about that path are easy to break and hard to read when broken:

  * It has to accept *statements*, not just expressions. #631 reported that any
    script containing an `if` failed on camoufox 0.4.11 while the equivalent
    ternary worked. The error said "Execution context was destroyed, most likely
    because of a navigation", which is what Playwright substitutes for every
    callFunction protocol error (ffExecutionContext.js rewriteError) -- so a
    syntax error in the wrapper reads as a phantom navigation.
  * It has to speak Playwright's call-argument wire format in both directions.
    Returning plain JSON is not enough: the client parses `{a: ...}` as a
    serialized array and `{v: ...}` as a serialized primitive, so a page
    returning `{a: 1}` would come back mangled.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/main-world-eval.py
(without the env var it uses the camoufox-managed browser download.)
Against an unpackaged objdir build, run `make stage-fonts` first: these launch
through AsyncCamoufox, which sets FONTCONFIG_FILE, and a build with no bundled
fonts fails startup in a way that surfaces as a confusing TargetClosedError.

What PASS means:
    * with main_world_eval=False, "mw:" is refused with a message that says so,
      rather than being silently evaluated somewhere else;
    * with main_world_eval=True, "mw:" reaches page globals and page functions,
      accepts statements and arguments, round-trips values Playwright's format
      would otherwise corrupt, awaits promises, and reports page errors with
      their real message;
    * writes made through "mw:" are visible to page script;
    * unprefixed evaluation stays isolated even with the flag on.
"""

import asyncio
import os
import sys
from typing import Any, Dict, List, Tuple

from camoufox.async_api import AsyncCamoufox

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

PAGE = """
<button id="probe">probe</button>
<script>
  window.pageSecret = 41;
  window.pageAdd = (a, b) => a + b;
  document.querySelector('#probe').addEventListener('click', () => {
    document.documentElement.dataset.sawMainWorldWrite = String(window.writtenFromMw);
  });
</script>
"""

# (label, script, expected) -- each run with the "mw:" prefix.
STATEMENT_CASES: List[Tuple[str, str, Any]] = [
    ("object literal", "({foo: 'bar'})", {"foo": "bar"}),
    ("ternary", "true ? ({foo: 'bar'}) : ({foo: 'baz'})", {"foo": "bar"}),
    ("if statement", "if (true) { ({foo: 'bar'}) } else { ({foo: 'baz'}) }", {"foo": "bar"}),
    ("if numeric", "if (true) { 1 } else { 2 }", 1),
    ("let + if", "let x = 1; if (x) { x = 2 }; x", 2),
    ("block", "{ 41 + 1 }", 42),
    ("arrow IIFE with if", "(() => { if (true) { return 1 } return 2 })()", 1),
]

# Shapes the client would misread if results came back as plain JSON rather than
# in Playwright's serialized form.
SERIALIZER_CASES: List[Tuple[str, str, Any]] = [
    ("object keyed 'a'", "({a: 1})", {"a": 1}),
    ("object keyed 'o'", "({o: 'x'})", {"o": "x"}),
    ("object keyed 'v'", "({v: 'null'})", {"v": "null"}),
    ("object keyed 'h'", "({h: 0})", {"h": 0}),
    ("nested", "({a: {b: [1, {c: 2}]}})", {"a": {"b": [1, {"c": 2}]}}),
    ("array", "[1, 'two', null]", [1, "two", None]),
    ("null", "null", None),
    ("undefined", "undefined", None),
    ("empty string", "''", ""),
    ("zero", "0", 0),
    ("false", "false", False),
]


def _launch_kwargs(main_world_eval: bool) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(headless=True, os="linux", main_world_eval=main_world_eval)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


def _check(results: Dict[str, Any], label: str, got: Any, expected: Any) -> None:
    ok = got == expected and type(got) is type(expected)
    results[label] = ok
    verdict = "PASS" if ok else "FAIL"
    suffix = "" if ok else f" (expected {expected!r})"
    print(f"  {verdict} {label:38} -> {got!r}{suffix}")


async def _run_disabled() -> bool:
    results: Dict[str, Any] = {}
    print("\n=== main_world_eval=False ===")
    async with AsyncCamoufox(**_launch_kwargs(False)) as browser:
        page = await browser.new_page()
        await page.set_content(PAGE)

        message = None
        try:
            await page.evaluate("mw:window.pageSecret")
        except Exception as exc:  # noqa: BLE001 - the message is the point
            message = str(exc).splitlines()[0]
        print(f"       refusal: {message}")
        _check(
            results,
            "mw: refused with a usable message",
            message is not None and "main_world_eval" in message,
            True,
        )
        # Refusing but evaluating the script anyway would be worse than the error.
        _check(results, "unprefixed evaluation unaffected", await page.evaluate("1 + 1"), 2)
        _check(results, "still isolated", await page.evaluate("window.pageSecret"), None)
    return all(results.values())


async def _run_enabled() -> bool:
    results: Dict[str, Any] = {}
    print("\n=== main_world_eval=True ===")
    async with AsyncCamoufox(**_launch_kwargs(True)) as browser:
        page = await browser.new_page()
        await page.set_content(PAGE)

        print("  -- reaching the page --")
        _check(results, "page global", await page.evaluate("mw:window.pageSecret"), 41)
        _check(results, "page function", await page.evaluate("mw:window.pageAdd(1, 2)"), 3)
        _check(results, "unprefixed stays isolated", await page.evaluate("window.pageSecret"), None)

        print("  -- statements (#631) --")
        for label, script, expected in STATEMENT_CASES:
            try:
                got: Any = await page.evaluate("mw:" + script)
            except Exception as exc:  # noqa: BLE001
                got = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            _check(results, label, got, expected)

        print("  -- arguments --")
        _check(results, "one argument", await page.evaluate("mw:(x) => x * 2", 21), 42)
        _check(results, "two arguments", await page.evaluate("mw:(a) => a[0] + a[1]", ["4", "2"]), "42")
        _check(results, "object argument", await page.evaluate("mw:(o) => o.a.b", {"a": {"b": 7}}), 7)
        _check(results, "argument meets page state", await page.evaluate("mw:(x) => x + window.pageSecret", 1), 42)

        print("  -- result round-trips --")
        for label, script, expected in SERIALIZER_CASES:
            _check(results, label, await page.evaluate("mw:" + script), expected)
        _check(results, "promise is awaited", await page.evaluate("mw:Promise.resolve('later')"), "later")
        _check(
            results,
            "date round-trips",
            (await page.evaluate("mw:new Date('2020-01-02T03:04:05.000Z')")).timestamp(),
            1577934245.0,
        )

        print("  -- writes land in the page --")
        await page.evaluate("mw:window.writtenFromMw = 'from-mw'")
        await page.click("#probe")
        _check(
            results,
            "page script sees the write",
            await page.get_attribute("html", "data-saw-main-world-write"),
            "from-mw",
        )

        print("  -- errors --")
        message = None
        try:
            await page.evaluate("mw:definitelyNotDefined.field")
        except Exception as exc:  # noqa: BLE001
            message = str(exc).splitlines()[0]
        print(f"       page error: {message}")
        _check(
            results,
            "page error keeps its message",
            message is not None and "definitelyNotDefined is not defined" in message,
            True,
        )

        message = None
        try:
            await page.evaluate_handle("mw:window")
        except Exception as exc:  # noqa: BLE001
            message = str(exc).splitlines()[0]
        print(f"       handle refusal: {message}")
        _check(
            results,
            "handle request refused clearly",
            message is not None and "handle" in message,
            True,
        )
    return all(results.values())


async def main() -> int:
    passed = True
    if not await _run_disabled():
        passed = False
    if not await _run_enabled():
        passed = False

    print()
    if passed:
        print("PASS: main world evaluation behaves")
    else:
        print("FAIL: main world evaluation is broken")
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
