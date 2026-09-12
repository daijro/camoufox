"""Does any one browser mechanism leak when driven hard?

Motivated by daijro/camoufox#762, where an ad-heavy page grows a content process
to ~15 GB while the parent stays flat. Reproducing that needs the real page and
a couple of minutes; what does not is the *shape* of it.

Method: drive one mechanism N times, then 4N times, and compare how much the
content process grew. A bounded implementation costs about the same either way,
because the peak is set by how much is alive at once. A per-iteration leak costs
about four times as much, because the cost is paid per iteration and never
returned. Measuring the slope rather than the total is what makes this work at
N=400 in seconds instead of needing the 15 GB.

Each mechanism is churned in isolation, so a failure names a culprit -- iframes,
canvas readback, WebGL contexts, workers, script compilation, font measurement --
rather than reporting that memory went up. Every page is served from loopback:
no network, no ad rotation, byte-identical every run.

The theory being tested is that Camoufox adds per-something state stock Firefox
has no equivalent of -- an isolated world per document, a noise seed per canvas,
a spoofed list per font family -- and that something churning fast enough
accumulates it.

Result at the time of writing: all six mechanisms passed at n=150 vs n=600
against v152.0.4-beta.30, so none of them leaks per iteration at that scale.

What that does NOT establish, and the reason this file is a detector rather than
an answer to #762:

  * a leak that only becomes visible past a few thousand iterations;
  * a leak in the *combination* -- #762's page runs all of these at once, and
    an isolated world per cross-origin iframe is not the same object as one per
    same-origin srcdoc frame;
  * anything that needs real ad content: cross-origin frames, live network,
    asm.js compilation at scale, video;
  * the runaway in #762 itself, which needs that page.

A pass here is evidence against a per-iteration leak in the mechanism tested. It
is not evidence that #762 is fixed, and this file should not be cited as such.
"""

from __future__ import annotations

import asyncio

import pytest

from _chaos import BROWSER, WEB_CONTENT, bounded, descendants, wait_for_process
from _churn import BODIES, ChurnServer

pytestmark = pytest.mark.asyncio

# Small enough to stay quick, large enough that a per-iteration leak of even a
# few KB is visible above the noise.
BASE_N = 150
FACTOR = 4

# A leak scales with the count; bounded overhead does not. Requiring the 4x run
# to stay under 2.5x the base leaves room for allocator behaviour and JIT warmup
# while still failing a genuine per-iteration leak, which lands at ~4x.
MAX_SLOPE = 2.5

# Below this, the numbers are allocator noise and the ratio is meaningless.
NOISE_FLOOR_MB = 12.0


async def _churn(binary, server, mechanism: str, n: int, psutil_mod) -> float:
    """Run one churn page and return the content process's growth, in MB."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(
        executable_path=str(binary), headless=True, i_know_what_im_doing=True
    ) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("about:blank")

        content = wait_for_process(psutil_mod, WEB_CONTENT, timeout=60)[0]
        baseline = content.memory_info().rss

        await page.goto(server.url(mechanism, n), wait_until="load", timeout=120_000)

        # The page sets window.__done when the loop finishes.
        deadline = asyncio.get_running_loop().time() + 180
        while asyncio.get_running_loop().time() < deadline:
            try:
                if await page.evaluate("window.__done"):
                    break
            except BaseException:
                break
            await asyncio.sleep(0.5)

        # Let the collector run before measuring, so this is retained memory
        # rather than garbage that simply has not been swept yet.
        await asyncio.sleep(3)
        try:
            peak = content.memory_info().rss
        except psutil_mod.NoSuchProcess:
            pytest.fail(
                f"the content process died churning {mechanism} at n={n}. That is #762's "
                "symptom, reached without an ad in sight."
            )
        await context.close()

    return (peak - baseline) / (1024 * 1024)


@pytest.mark.parametrize("mechanism", sorted(BODIES))
async def test_mechanism_does_not_leak_per_iteration(binary, psutil_mod, mechanism):
    """Growth must not scale with how many times the mechanism ran."""
    with ChurnServer() as server:
        small = await _churn(binary, server, mechanism, BASE_N, psutil_mod)
        large = await _churn(binary, server, mechanism, BASE_N * FACTOR, psutil_mod)

    if max(small, large) < NOISE_FLOOR_MB:
        pytest.skip(
            f"{mechanism}: growth stayed under the noise floor "
            f"({small:.1f} MB at n={BASE_N}, {large:.1f} MB at n={BASE_N * FACTOR}); "
            "nothing to measure a slope against"
        )

    slope = large / max(small, 1.0)
    assert slope <= MAX_SLOPE, (
        f"{mechanism} grows with iteration count: {small:.1f} MB at n={BASE_N} vs "
        f"{large:.1f} MB at n={BASE_N * FACTOR} ({slope:.1f}x for {FACTOR}x the work). "
        "Bounded overhead does not scale like that -- something is retained per "
        "iteration. This is the shape daijro/camoufox#762 reaches on a real page."
    )


async def test_the_parent_does_not_grow_while_a_content_process_churns(binary, psutil_mod):
    """#762 measured the parent flat at 479 MB while a child reached 15 GB.

    Containment is a property in its own right: if churn in one tab pushed the
    parent up, one bad page would degrade every other tab in the browser.
    """
    from camoufox.async_api import AsyncCamoufox

    with ChurnServer() as server:
        async with AsyncCamoufox(
            executable_path=str(binary), headless=True, i_know_what_im_doing=True
        ) as browser:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("about:blank")

            parent = wait_for_process(psutil_mod, BROWSER, timeout=60)[0]
            baseline = parent.memory_info().rss

            for mechanism in ("iframe", "canvas", "script"):
                await page.goto(server.url(mechanism, BASE_N * 2), wait_until="load",
                                timeout=120_000)
                await asyncio.sleep(2)

            await asyncio.sleep(3)
            growth_mb = (parent.memory_info().rss - baseline) / (1024 * 1024)
            await context.close()

    assert growth_mb < 250, (
        f"the browser parent grew {growth_mb:.0f} MB while a content process did the "
        "churning. Work in one tab is meant to stay in that tab's process."
    )
