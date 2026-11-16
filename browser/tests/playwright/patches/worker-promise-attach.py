"""
Verify that a worker evaluation whose promise cannot be observed fails
instead of waiting forever.

A worker has no Xrays, so Runtime.js waits for an evaluated promise the way
upstream Juggler does: it runs `p.then(() => { debugger; }, ...)` in the
worker's own global and sweeps its pending promises from onDebuggerStatement.
That `then` is whatever the worker's script put on Promise.prototype. If it
throws, no reaction is attached, the pending entry stays registered, and
worker.evaluate() never returns: the driver hangs on a page's say-so. The
attach failure must reject the evaluation with an error, leave nothing
pending, and later evaluations in the same worker must still work.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python browser/tests/playwright/patches/worker-promise-attach.py
(without the env var it uses the camoufox-managed browser download.)

What PASS means:
    * in a worker whose Promise.prototype.then throws, evaluating a pending
      promise rejects with an error within the deadline (no hang);
    * a plain evaluation in that worker still returns its value afterwards;
    * in an untouched worker, the same pending promise resolves to its value.
"""

import asyncio
import json
import sys

from camoufox.async_api import AsyncCamoufox
from helpers import launch_kwargs

# A promise that settles shortly after the evaluation starts, so the driver
# has to attach a reaction and wait for it.
PENDING = "new Promise(r => setTimeout(() => r(41 + 1), 50))"
# Far above a working evaluation's few milliseconds; a hang never returns.
DEADLINE_S = 10

WORKER_PAGE = """<body><script>
const src = %s;
window.worker = new Worker(URL.createObjectURL(new Blob([src], {type: "text/javascript"})));
</script></body>"""
BREAK_THEN = "Promise.prototype.then = function () { throw new Error('then replaced by the page'); };"


PAGE_URL = "https://worker.camoufox.test/"


async def _worker(page, script):
    """A dedicated worker running `script`, started by a page on a real origin
    (about:blank, which set_content uses, starts none)."""
    body = WORKER_PAGE % json.dumps(script)
    await page.route(PAGE_URL, lambda route: route.fulfill(status=200, content_type="text/html", body=body))
    async with page.expect_worker() as info:
        await page.goto(PAGE_URL)
    await page.unroute(PAGE_URL)
    return await info.value


async def main() -> int:
    passed = True
    async with AsyncCamoufox(**launch_kwargs(os="linux")) as browser:
        page = await browser.new_page()

        worker = await _worker(page, "self.ready = true;")
        value = await asyncio.wait_for(worker.evaluate(PENDING), DEADLINE_S)
        print(f"untouched worker: pending promise -> {value!r}")
        if value != 42:
            passed = False
            print("  FAIL: expected 42")

        worker = await _worker(page, BREAK_THEN)
        try:
            value = await asyncio.wait_for(worker.evaluate(PENDING), DEADLINE_S)
            passed = False
            print(f"  FAIL: resolved to {value!r}; the replaced then() should have made it unobservable")
        except asyncio.TimeoutError:
            passed = False
            print(f"  FAIL: worker.evaluate() still pending after {DEADLINE_S}s (hang)")
        except Exception as e:
            print(f"then() replaced: pending promise rejected: {str(e).splitlines()[0]}")

        try:
            value = await asyncio.wait_for(worker.evaluate("6 * 7"), DEADLINE_S)
            print(f"then() replaced: plain evaluation afterwards -> {value!r}")
            if value != 42:
                passed = False
                print("  FAIL: expected 42")
        except Exception as e:
            passed = False
            print(f"  FAIL: plain evaluation afterwards failed: {type(e).__name__}: {e}")

    print("PASS: an unobservable worker promise fails fast" if passed else
          "FAIL: worker promise attach")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
