"""
Verify the renderer-ack wait is bounded (daijro/camoufox#751, #752).

This guards the backstop itself -- the one mechanism that makes an undelivered
input event survivable rather than fatal.

Camoufox dispatches synthesized mouse events inside `activateAndRun()`
(additions/juggler/TargetRegistry.js), which serializes every dispatch on a
*process-global* promise chain. Each dispatch awaits a hit-renderer ack. Before
the backstop that wait was unbounded, so an ack that never arrived did not lose
one event -- it wedged every later input event in the process, in every tab,
permanently, at 0% CPU with no diagnostic. All four shipped deadlocks were that
failure with four different triggers; see docs/input-dispatch.md.

`MouseDispatch.sendAcked()` now waits at most `kAckDeadlineMs`, then drops the
event with a warning and lets the chain advance.

HOW THIS TEST WORKS
The ack is delivered from the content main thread, so blocking that thread
delays it by exactly the block duration -- a legitimate mechanism for producing
a late ack, with no test-only hook in production code. The page is made to block
for well over the deadline; a bounded wait returns in about the deadline, an
unbounded one waits for the whole block.

The gap is what makes the assertion meaningful: with a ~5s deadline and a 40s
block, "returned in under 20s" cannot be satisfied by an unbounded wait, and
does not depend on the exact deadline value.

Dropping that event is the correct, chosen behaviour: warn and continue. The
test therefore asserts recovery, not delivery -- the move may legitimately be
lost, but the browser must still be usable afterwards.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python3 browser/tests/playwright/patches/input-ack-backstop.py

What PASS means:
    * a dispatch whose ack is late by far more than the deadline returns in
      roughly the deadline, not in the block duration;
    * once the block clears, input still works -- the chain advanced rather
      than being abandoned mid-slot.

Before the backstop the first move waits out the entire block.
"""

import asyncio
import os
import sys
import time

from camoufox.async_api import AsyncCamoufox

# Far longer than kAckDeadlineMs (5s), so the two outcomes cannot be confused.
BLOCK_MS = 40000
# Generous over the deadline, far under the block.
BOUNDED_S = 20
RECOVERY_TIMEOUT_S = 30

EXECUTABLE_PATH = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")


def _launch_kwargs():
    kwargs = dict(headless=True, os="windows", humanize=False)
    if EXECUTABLE_PATH:
        kwargs["executable_path"] = EXECUTABLE_PATH
    return kwargs


async def main() -> int:
    print("\n=== bounded renderer-ack wait ===")
    async with AsyncCamoufox(**_launch_kwargs()) as browser:
        page = await browser.new_page()
        await page.set_content('<body style="margin:0;height:1200px"></body>')
        await page.evaluate(
            "window.__moves=0;addEventListener('mousemove',()=>window.__moves++)")
        await asyncio.wait_for(page.mouse.move(300, 300), timeout=RECOVERY_TIMEOUT_S)

        # Block the content main thread. Deliberately not awaited: the block has
        # to still be running when the move below is dispatched.
        blocker = asyncio.ensure_future(page.evaluate(
            f"(()=>{{const end=Date.now()+{BLOCK_MS};while(Date.now()<end);}})()"))
        await asyncio.sleep(0.25)

        print(f"  content main thread blocked for {BLOCK_MS}ms; dispatching a move",
              flush=True)
        t0 = time.time()
        try:
            await asyncio.wait_for(page.mouse.move(500, 400), timeout=BOUNDED_S)
        except asyncio.TimeoutError:
            print(f"  FAIL: still waiting after {BOUNDED_S}s")
            print(
                "\n  The ack wait is unbounded. An event that never reaches the\n"
                "  renderer will wedge the process-global activation chain forever.\n"
                "  Fix: bound it in MouseDispatch.sendAcked() via\n"
                "  EventWatcher.ensureEventWithin(). See docs/input-dispatch.md.\n")
            blocker.cancel()
            return 1
        waited = time.time() - t0
        print(f"  returned after {waited:.1f}s (block runs for {BLOCK_MS / 1000:.0f}s)",
              flush=True)

        # Let the block finish, then prove the chain advanced rather than died.
        try:
            await asyncio.wait_for(blocker, timeout=BLOCK_MS / 1000 + 15)
        except asyncio.TimeoutError:
            print("  FAIL: the blocking script never finished")
            return 1
        except Exception:
            pass  # a lost evaluate is fine; the chain is what matters

        before = await asyncio.wait_for(
            page.evaluate("window.__moves"), timeout=RECOVERY_TIMEOUT_S)
        try:
            await asyncio.wait_for(page.mouse.move(700, 500), timeout=RECOVERY_TIMEOUT_S)
            await asyncio.wait_for(page.mouse.click(650, 450), timeout=RECOVERY_TIMEOUT_S)
            after = await asyncio.wait_for(
                page.evaluate("window.__moves"), timeout=RECOVERY_TIMEOUT_S)
        except asyncio.TimeoutError:
            print("  FAIL: input dead after the late ack -- the chain is poisoned")
            return 1
        if after <= before:
            print("  FAIL: the browser accepted moves but the page saw none")
            return 1

        print(f"  input still live afterwards ({after - before} mousemove seen)")
        print("\n  PASS: the ack wait is bounded and the chain recovers\n")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
