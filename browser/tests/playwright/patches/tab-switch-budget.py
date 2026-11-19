r"""
A tab switch that never completes cannot wedge input (docs/input-dispatch.md).

`activateAndRun()` (additions/juggler/TargetRegistry.js) serializes every input
command on a process-global chain and bounds each slot at 30s. It used to wait
for the `TabSwitchDone` event before arming that bound, so an event that never
fired stalled the chain, and every later input command in every tab, with no
way out. It also left its event listener on the window.

The guard opens a second tab from the first page, so the first is a background
tab of the same window, and makes a capturing listener on the window swallow
`TabSwitchDone` (Marionette's chrome context). A mouse move on the background
page must then fail once the slot budget expires, since its input never ran,
and leave no `TabSwitchDone` listener on the window. Once the event flows
again, the page must see a later move, and not the one that expired.

Every browser call is bounded, so a returning deadlock fails here in about a
minute, with the browser closed, instead of at the runner's timeout.

    python browser/tests/playwright/patches/tab-switch-budget.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, marionette_env, resolve_binary  # noqa: E402

SLOT_BUDGET_S = 30
# Past the budget, far short of "never": an unbounded wait cannot satisfy it.
BOUNDED_S = SLOT_BUDGET_S + 20
RECOVERY_S = 10

WAITERS = """
const win = Services.wm.getMostRecentWindow("navigator:browser");
return Services.els.getListenerInfoFor(win)
  .filter(info => info.type == "TabSwitchDone" && !info.capturing).length;
"""

SWALLOW = """
const win = Services.wm.getMostRecentWindow("navigator:browser");
win.__swallowTabSwitchDone = e => e.stopImmediatePropagation();
win.addEventListener("TabSwitchDone", win.__swallowTabSwitchDone, true);
"""

RELEASE = """
const win = Services.wm.getMostRecentWindow("navigator:browser");
win.removeEventListener("TabSwitchDone", win.__swallowTabSwitchDone, true);
"""

RECORD_MOVES = """() => {
  window.__moves = [];
  document.addEventListener("mousemove", e => window.__moves.push([e.clientX, e.clientY]));
}"""


def seen(moves, x, y):
    return any(abs(mx - x) <= 1 and abs(my - y) <= 1 for mx, my in moves)


async def check(background, front, m) -> list:
    failures = []
    baseline = m.js(WAITERS)
    m.js(SWALLOW)

    started = time.time()
    error = None
    try:
        await asyncio.wait_for(background.mouse.move(100, 100), BOUNDED_S)
    except asyncio.TimeoutError:
        failures.append(f"the move did not return within {BOUNDED_S}s; the slot budget does not bound the tab switch")
        return failures
    except Exception as exc:  # the expected outcome: the slot expired before its input ran
        error = exc
    waited = time.time() - started
    print(f"  move on a background tab, TabSwitchDone swallowed: returned after {waited:.1f}s"
          f" ({'error: ' + str(error).splitlines()[0] if error else 'no error'})")
    if waited < SLOT_BUDGET_S - 5:
        failures.append(f"the move returned after {waited:.1f}s, before the {SLOT_BUDGET_S}s slot"
                        " budget, so the tab switch never waited and the check proves nothing")
    if error is None:
        failures.append("the move reported success although its input never ran")
    leaked = m.js(WAITERS) - baseline
    print(f"  TabSwitchDone listeners left behind: {leaked}")
    if leaked:
        failures.append(f"{leaked} TabSwitchDone listener(s) left on the window after the slot expired")

    m.js(RELEASE)
    try:
        await asyncio.wait_for(front.bring_to_front(), RECOVERY_S)
        await asyncio.wait_for(background.mouse.move(200, 200), RECOVERY_S)
        moves = await asyncio.wait_for(background.evaluate("window.__moves"), RECOVERY_S)
    except asyncio.TimeoutError:
        failures.append(f"input after the expired slot did not complete within {RECOVERY_S}s; the chain is stalled")
        return failures
    print(f"  page saw after recovery: {moves}")
    if not seen(moves, 200, 200):
        failures.append("the page never saw the move sent after the event flowed again")
    if seen(moves, 100, 100):
        failures.append("the expired move reached the page late")
    return failures


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    port = free_port()
    with hidden_display():
        async with AsyncCamoufox(
                headless=False, executable_path=str(resolve_binary()), args=marionette_args(), env=marionette_env(),
                firefox_user_prefs={"marionette.port": port}, humanize=False, i_know_what_im_doing=True) as browser:
            context = await browser.new_context()
            background = await context.new_page()
            await asyncio.wait_for(background.set_content("<body style='margin:0;height:100vh'></body>"), RECOVERY_S)
            await asyncio.wait_for(background.evaluate(RECORD_MOVES), RECOVERY_S)
            # A page-opened window is a tab in the same window and is selected, so
            # `background` has to be switched to; context.new_page() would open a
            # separate window and need no tab switch.
            async with background.expect_popup() as popup_info:
                await background.evaluate("() => { window.open('about:blank'); }")
            front = await popup_info.value
            m = Marionette(port)
            try:
                failures = await check(background, front, m)
            finally:
                m.close()
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a tab switch that never completes fails its own command, not the chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
