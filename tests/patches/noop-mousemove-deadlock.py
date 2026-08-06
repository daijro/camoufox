"""
Verify a zero-displacement (no-op) mousemove does not deadlock the input chain.

Camoufox dispatches synthesized mouse events inside `activateAndRun()`
(additions/juggler/TargetRegistry.js), which serializes every dispatch on a
*process-global* promise chain. Each dispatch awaits a `hit-renderer` ack from
the content process. If an ack never arrives, the callback never returns, the
global chain never advances, and every later input event in the process hangs
behind it forever. (Same activation-chain machinery as daijro/camoufox#225, but
a distinct trigger.)

The trigger here is a mousemove whose destination rounds to the pixel the
pointer is ALREADY on. The widget coalesces it away and dispatches no
`eMouseMove`, so no `juggler-mouse-event-hit-renderer` notification is ever
produced and the awaited ack never arrives.

It bites in practice because the pointer starts at (0,0)
(`PageHandler.js` `this._lastTrackedPos = { x: 0, y: 0 }`), so the FIRST mouse
action of a session deadlocks whenever it targets that pixel:

    page.mouse.move(0, 0)      # exact origin
    page.mouse.move(0.4, 0.4)  # rounds to (0, 0)

Any humanized driver whose cursor model initialises to 0,0 and whose first move
is a short hop near the corner reaches this.

Fix (PageHandler.js, the `type === 'mousemove'` branch): if the rounded
destination equals the rounded current position, record the position and return
without dispatching — a no-op move has nothing to send.

HOW THIS TEST WORKS
- Sync API. The bug only manifests through Playwright's *sync* client: the async
  client dedupes a move to the current position and never sends it, so the
  redundant dispatch never reaches juggler. camoufox's sync_api is a headline
  interface, so this path is worth guarding.
- Child process. A hung sync call cannot be timed out in-process, and a wedged
  browser also hangs `close()`, so the work runs in a child the parent bounds
  with a timeout and kills on hang.
- Several fresh pages per run. Whether (0,0) is a widget no-op depends on the
  window's screen offset, which the randomized default fingerprint varies, so a
  single page reproduces only ~80% of the time. Each fresh page is an
  independent chance (its pointer starts at 0,0); across PAGES_PER_RUN the run
  reproduces deterministically on a headless Linux host. On a build WITH the
  fix, every page completes quickly and the run passes.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python3 tests/patches/noop-mousemove-deadlock.py

Before the fix the child hangs on whichever page first reproduces and is killed.
After it, every page completes and a genuine move still fires a mousemove.
"""

import os
import subprocess
import sys

CHILD_ENV = "_NOOP_DEADLOCK_CHILD"
CHILD_TIMEOUT_S = 90
PAGES_PER_RUN = 6
# Both round to the origin, so both are no-op first moves. Alternated across the
# fresh pages below.
NOOP_TARGETS = [(0.0, 0.0), (0.4, 0.4)]

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")


def _run_child() -> int:
    """Open several fresh pages; each does a no-op first move then a real move."""
    from camoufox.sync_api import Camoufox

    # Default fingerprint on purpose — see the module docstring on why (0,0) must
    # land on the window corner for the stock build to coalesce it into a no-op.
    kwargs = dict(headless=True)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH

    with Camoufox(**kwargs) as browser:
        for i in range(PAGES_PER_RUN):
            x, y = NOOP_TARGETS[i % len(NOOP_TARGETS)]
            print(f"    page {i + 1}/{PAGES_PER_RUN}: first move -> ({x}, {y})", flush=True)
            page = browser.new_page()
            page.goto("about:blank")
            # Session's first mouse action, from the initial (0,0): a no-op.
            # On a stock build this never returns and the parent kills us.
            page.mouse.move(x, y)
            # The activation chain must not be poisoned: a real move still fires.
            page.evaluate(
                "window.__ok=false;"
                "addEventListener('mousemove',()=>window.__ok=true,{once:true})"
            )
            page.mouse.move(400, 300)
            if not page.evaluate("window.__ok"):
                print(f"    page {i + 1}: genuine move produced no mousemove", flush=True)
                return 2
            page.close()
    return 0


def main() -> int:
    print("\n=== no-op first mousemove ===")
    env = {**os.environ, CHILD_ENV: "1"}
    try:
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__)],
            env=env, timeout=CHILD_TIMEOUT_S,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        sys.stdout.write((e.stdout or b"").decode(errors="replace"))
        print(f"\n  FAIL: hung > {CHILD_TIMEOUT_S}s")
        print(
            "\n  DEADLOCK: a no-op mousemove (destination rounds to the current pixel)\n"
            "  produced no eMouseMove and no hit-renderer ack. The global activation\n"
            "  chain is wedged -- all further input hangs.\n"
            "  Fix: skip zero-displacement moves in PageHandler.js (mousemove branch).\n"
        )
        return 1

    sys.stdout.write(r.stdout.decode(errors="replace"))
    if r.returncode == 0:
        print("\n  PASS: every no-op first move completed; input still live; chain not poisoned\n")
        return 0
    print(f"\n  FAIL: child exit {r.returncode}")
    return 1


if __name__ == "__main__":
    if os.environ.get(CHILD_ENV):
        sys.exit(_run_child())
    sys.exit(main())
