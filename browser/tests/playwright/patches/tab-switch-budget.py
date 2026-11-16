r"""
A tab switch that never completes cannot wedge input (docs/input-dispatch.md).

`activateAndRun()` (additions/juggler/TargetRegistry.js) serializes every input
command on a process-global chain and bounds each slot at 30s. It used to wait
for the `TabSwitchDone` event before arming that bound, so an event that never
fired stalled the chain, and every later input command in every tab, with no
way out. It also left its event listener on the window.

The guard opens a second tab from the first page, so the first is a background
tab of the same window, and makes a capturing listener on the window swallow
`TabSwitchDone` (Marionette's chrome context). A mouse move on the background page must then return once the
slot budget expires, leave no `TabSwitchDone` listener on the window, and a
later move must still complete quickly once the event flows again.

    python browser/tests/playwright/patches/tab-switch-budget.py
"""

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


def main() -> int:
    from camoufox.sync_api import Camoufox

    port = free_port()
    failures = []
    with hidden_display(), Camoufox(
            headless=False, executable_path=str(resolve_binary()), args=marionette_args(), env=marionette_env(),
            firefox_user_prefs={"marionette.port": port}, humanize=False, i_know_what_im_doing=True) as browser:
        context = browser.new_context()
        background = context.new_page()
        # A page-opened window is a tab in the same window and is selected, so
        # `background` has to be switched to; context.new_page() would open a
        # separate window and need no tab switch.
        with background.expect_popup() as popup_info:
            background.evaluate("() => { window.open('about:blank'); }")
        front = popup_info.value
        m = Marionette(port)
        try:
            baseline = m.js(WAITERS)
            m.js(SWALLOW)
            started = time.time()
            background.mouse.move(100, 100)
            waited = time.time() - started
            print(f"  move on a background tab, TabSwitchDone swallowed: returned after {waited:.1f}s")
            if waited < SLOT_BUDGET_S - 5:
                failures.append(f"the move returned after {waited:.1f}s, before the {SLOT_BUDGET_S}s slot"
                                " budget, so the tab switch never waited and the check proves nothing")
            if waited > BOUNDED_S:
                failures.append(f"the move took {waited:.1f}s; the slot budget does not bound the tab switch")
            leaked = m.js(WAITERS) - baseline
            print(f"  TabSwitchDone listeners left behind: {leaked}")
            if leaked:
                failures.append(f"{leaked} TabSwitchDone listener(s) left on the window after the slot expired")

            m.js(RELEASE)
            front.bring_to_front()
            started = time.time()
            background.mouse.move(200, 200)
            waited = time.time() - started
            print(f"  next move, event flowing again: returned after {waited:.1f}s")
            if waited > RECOVERY_S:
                failures.append(f"input after the expired slot took {waited:.1f}s; the chain is still stalled")
        finally:
            m.close()
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a tab switch that never completes costs one slot budget, not the chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
