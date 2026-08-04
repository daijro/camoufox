"""
Verify main-world evaluation accepts statements, not just expressions (daijro/camoufox#631).

Camoufox evaluates page scripts through its own main-world path (the
`main_world_eval` launch flag and the juggler evaluation handler) rather than
Playwright's default isolated world. That path has to wrap whatever string it
is handed so a bare *statement* -- `if (...) { ... }`, `let x = 1;`, a block --
still produces a value instead of a syntax error.

#631 reported that any script containing an `if` statement failed with
"Execution context was destroyed" on camoufox 0.4.11, while the equivalent
ternary worked. That symptom is gone on current builds, so this test pins the
behaviour: the wrapping is easy to break again during a Juggler rebase, and the
failure mode is a hard error on the caller's side rather than anything the
build catches.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python tests/patches/main-world-eval.py
(without the env var it uses the camoufox-managed browser download.)

What PASS means:
    * expressions (object literal, ternary, arrow IIFE) evaluate to their value;
    * statements (`if`, `let` + reassignment, block) evaluate without raising
      and return the expected completion value;
    * both main_world_eval=True and main_world_eval=False behave identically,
      so neither path regresses independently.
"""

import asyncio
import os
import sys
from typing import Any, Dict, List, Tuple

from camoufox.async_api import AsyncCamoufox

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")

# (label, script, expected)
CASES: List[Tuple[str, str, Any]] = [
    ("object literal", "({foo: 'bar'})", {"foo": "bar"}),
    ("ternary", "true ? ({foo: 'bar'}) : ({foo: 'baz'})", {"foo": "bar"}),
    ("if statement", "if (true) { ({foo: 'bar'}) } else { ({foo: 'baz'}) }", {"foo": "bar"}),
    ("if numeric", "if (true) { 1 } else { 2 }", 1),
    ("let + if", "let x = 1; if (x) { x = 2 }; x", 2),
    ("arrow IIFE with if", "(() => { if (true) { return 1 } return 2 })()", 1),
]


def _launch_kwargs(main_world_eval: bool) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = dict(headless=True, os="linux", main_world_eval=main_world_eval)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


async def _run_cases(main_world_eval: bool) -> bool:
    ok = True
    async with AsyncCamoufox(**_launch_kwargs(main_world_eval)) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        print(f"\n=== main_world_eval={main_world_eval} ===")
        for label, script, expected in CASES:
            try:
                result = await page.evaluate(script)
            except Exception as exc:  # noqa: BLE001 - any raise is a failure here
                ok = False
                print(f"  FAIL {label:20} raised {type(exc).__name__}: {str(exc).splitlines()[0]}")
                continue
            if result == expected:
                print(f"  PASS {label:20} -> {result!r}")
            else:
                ok = False
                print(f"  FAIL {label:20} -> {result!r} (expected {expected!r})")
    return ok


async def main() -> int:
    passed = True
    for main_world_eval in (False, True):
        if not await _run_cases(main_world_eval):
            passed = False

    print()
    if passed:
        print("PASS: statements and expressions evaluate identically in both modes")
    else:
        print("FAIL: main-world evaluation rejected a script it should accept")
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
