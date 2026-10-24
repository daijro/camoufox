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

The drag scenario blocks the page for the same 40s in the mousemove that starts
a real drag, which also holds back the page's `juggler-drag-finalized` answer.
PASS means that move returns in about two deadlines, not in activateAndRun()'s
30s slot backstop, and the drag still drops once the page answers late.

The GPU-process scenario runs headful, on a private Xvfb display, with the GPU
process forced on (Linux runs none by default; Windows does). Every dispatch
asks the compositor to flush APZ repaints and waits for `apz-repaints-flushed`.
Killing the GPU process loses the flush in flight, so that wait never ends.
The test kills it during a burst of wheels, so a flush is in flight. PASS
means the burst returns in about one deadline, not the 30s slot backstop, and
input then lands where it was sent.
"""

import asyncio
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from camoufox.async_api import AsyncCamoufox
from helpers import hidden_display, launch_kwargs

# Far longer than kAckDeadlineMs (5s), so the two outcomes cannot be confused.
BLOCK_MS = 40000
# Generous over the deadline, far under the block.
BOUNDED_S = 20
RECOVERY_TIMEOUT_S = 30
GPU_KILLS = 2


async def main() -> int:
    print("\n=== bounded renderer-ack wait ===")
    async with AsyncCamoufox(**launch_kwargs(os="windows", humanize=False)) as browser:
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
        return await drag_on_busy_page(browser)


async def drag_on_busy_page(browser) -> int:
    print("\n=== drag whose page is busy when it starts ===")
    page = await browser.new_page()
    await page.set_content(
        '<body style="margin:0;height:1200px">'
        '<div id="src" draggable="true" style="width:200px;height:200px"></div>'
        '<div id="dst" style="position:absolute;left:400px;top:400px;width:200px;height:200px">'
        '</div></body>')
    await page.evaluate(
        "window.__log=[];window.__blocked=false;"
        "const src=document.getElementById('src'),dst=document.getElementById('dst');"
        "src.addEventListener('dragstart',e=>{e.dataTransfer.setData('text/plain','x');"
        "__log.push('dragstart')});"
        "src.addEventListener('dragend',()=>__log.push('dragend'));"
        "dst.addEventListener('dragover',e=>e.preventDefault());"
        "dst.addEventListener('drop',e=>{e.preventDefault();__log.push('drop')});"
        "addEventListener('click',()=>__log.push('click'));"
        "addEventListener('mousemove',()=>{if(!__log.length||__blocked)return;__blocked=true;"
        f"const end=Date.now()+{BLOCK_MS};while(Date.now()<end);}})")
    await asyncio.wait_for(page.mouse.move(100, 100), timeout=RECOVERY_TIMEOUT_S)
    await asyncio.wait_for(page.mouse.down(), timeout=RECOVERY_TIMEOUT_S)
    t0 = time.time()
    try:
        await asyncio.wait_for(page.mouse.move(300, 300), timeout=BOUNDED_S)
    except asyncio.TimeoutError:
        print(f"  FAIL: the move that started the drag still waits after {BOUNDED_S}s")
        return 1
    print(f"  returned after {time.time() - t0:.1f}s (block runs for {BLOCK_MS / 1000:.0f}s)")
    # Waits out the block; the page answers juggler-drag-finalized after it.
    await asyncio.wait_for(page.evaluate("1"), timeout=BLOCK_MS / 1000 + 15)
    await asyncio.wait_for(page.mouse.move(500, 500), timeout=RECOVERY_TIMEOUT_S)
    await asyncio.wait_for(page.mouse.up(), timeout=RECOVERY_TIMEOUT_S)
    log = await asyncio.wait_for(page.evaluate("__log"), timeout=RECOVERY_TIMEOUT_S)
    if log != ["dragstart", "drop", "dragend"]:
        print(f"  FAIL: the page saw {log}, not dragstart, drop, dragend")
        return 1
    print("\n  PASS: the drag wait is bounded and a late answer still drops\n")
    return await gpu_process_killed()


def gpu_process(binary):
    """This test's browser's GPU process: a descendant of this process."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            # A relaunched one comes from the fork server, which rewrites its
            # command line as one space-separated string.
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().replace(b"\0", b" ").decode(errors="replace").split()
            if argv[-1:] != ["gpu"] or os.path.realpath(argv[0]) != os.path.realpath(binary):
                continue
            p = int(pid)
            while p > 1:
                with open(f"/proc/{p}/stat") as f:
                    p = int(f.read().rsplit(")", 1)[1].split()[1])
                if p == os.getpid():
                    return int(pid)
        except OSError:
            continue
    return None


async def gpu_process_killed() -> int:
    print("\n=== scrolling while the GPU process dies ===")
    # In the profile's user.js: firefox_user_prefs reach CI's unpackaged build
    # after gfx has read these startup-only prefs, so it starts no GPU process.
    with tempfile.TemporaryDirectory() as profile, hidden_display():
        Path(profile, "user.js").write_text(
            'user_pref("layers.gpu-process.enabled", true);\n'
            'user_pref("layers.gpu-process.force-enabled", true);\n')
        kwargs = launch_kwargs(headless=False, os="linux", humanize=False,
                               persistent_context=True, user_data_dir=profile)
        binary = kwargs["executable_path"]
        async with AsyncCamoufox(**kwargs) as context:
            page = await context.new_page()
            await page.set_content('<body style="margin:0;height:200000px"></body>')
            await page.evaluate(
                "window.__clicks=[];addEventListener('click',e=>__clicks.push([e.clientX,e.clientY]))")
            sent = []
            killed = None
            for i in range(GPU_KILLS):
                # Let the relaunched GPU process come up first.
                for _ in range(10):
                    await asyncio.wait_for(page.mouse.wheel(0, 100), timeout=RECOVERY_TIMEOUT_S)
                pid = gpu_process(binary)
                if pid in (None, killed):
                    print("  FAIL: the browser runs no GPU process, so nothing was tested")
                    return 1
                # Back-to-back wheels keep a flush in flight almost all the time.
                t0 = time.time()
                burst = asyncio.gather(*[page.mouse.wheel(0, 100) for _ in range(30)])
                await asyncio.sleep(0.15)
                os.kill(pid, signal.SIGKILL)
                killed = pid
                try:
                    await asyncio.wait_for(burst, timeout=BOUNDED_S)
                except asyncio.TimeoutError:
                    print(f"  FAIL: the wheels still wait {BOUNDED_S}s after the GPU process died")
                    return 1
                print(f"  kill {i + 1}: 30 wheels returned after {time.time() - t0:.1f}s")
                sent.append([100 + i, 200])
                await asyncio.wait_for(page.mouse.click(*sent[-1]), timeout=RECOVERY_TIMEOUT_S)
            clicks = await page.evaluate("__clicks")
    if clicks != sent:
        print(f"  FAIL: clicks sent to {sent} landed at {clicks}")
        return 1
    print("\n  PASS: the APZ flush wait is bounded, and input lands where sent\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
