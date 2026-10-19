"""Launch browsers, kill them, and prove nothing was left behind.

The failure this suite exists for is not dramatic. It is a scraper that runs for
six hours, launches a browser per job, and then starts failing with "too many
open files" or refusing to allocate an X display -- because each round left one
descriptor, one zombie, or one stale /tmp/.X11-unix socket behind. Nothing in
the Playwright suite can see that: every one of its tests passes right up until
the process runs out of something.

Scope, stated plainly: these tests measure resources held by *this* process and
its children -- file descriptors, sockets, child processes, X11 artefacts, and
our own RSS. They do not inspect the browser's heap, and a test passing here is
not a claim that Gecko is leak-free internally. It is a claim that when Camoufox
says a browser is closed, the operating system agrees.
"""

from __future__ import annotations

import asyncio
import os
import resource
import signal
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def _launch_and_close(binary: Path, *, contexts: int = 1, pages: int = 1) -> None:
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as browser:
        for _ in range(contexts):
            context = await browser.new_context()
            for _ in range(pages):
                page = await context.new_page()
                await page.goto("about:blank")
            await context.close()


# ---------------------------------------------------------------------------


async def test_a_single_launch_leaves_nothing(binary, leak_check):
    await _launch_and_close(binary)
    leak_check.assert_clean()


async def test_repeated_launches_do_not_accumulate(binary, leak_check, request):
    """The important shape: N rounds must cost the same as one.

    A per-round leak is invisible at N=1 and fatal at N=500, so this asserts
    against the state before the *first* round rather than the previous one.
    """
    rounds = request.config.getoption("--rounds")
    for _ in range(rounds):
        await _launch_and_close(binary)
    leak_check.assert_clean()


async def test_concurrent_browsers_all_clean_up(binary, leak_check, request):
    """Several browsers alive at once, then all closed.

    Concurrency is where teardown bugs hide: a shared driver, a display number
    claimed twice, a close path that only works when it is the only one running.
    """
    count = request.config.getoption("--browsers")
    await asyncio.gather(*(_launch_and_close(binary) for _ in range(count)))
    leak_check.assert_clean()


async def test_many_contexts_in_one_browser_clean_up(binary, leak_check):
    await _launch_and_close(binary, contexts=5, pages=2)
    leak_check.assert_clean()


async def test_an_early_launch_failure_leaves_nothing(leak_check):
    """A launch that dies before Playwright starts.

    Camoufox resolves properties.json next to the binary, so a bad
    executable_path fails here -- before any session exists. Nothing to leak,
    but worth pinning: this is the path a typo takes, and it must not leave a
    half-built object behind either.
    """
    from camoufox.async_api import AsyncCamoufox

    with pytest.raises(BaseException):
        async with AsyncCamoufox(
            executable_path="/nonexistent/camoufox-bin",
            headless=True,
            i_know_what_im_doing=True,
        ):
            pass
    leak_check.assert_clean()


async def test_a_late_launch_failure_tears_down_the_session(binary, leak_check):
    """The actual rule from issue #82, on the path that actually has a session.

    The first version of this test used a bad executable path and proved
    nothing: Camoufox rejects that while looking for properties.json, before
    Playwright is ever started, so there was no driver to leak. A one
    millisecond launch timeout fails *after* the session is up, which is the
    case #82 was filed about -- and the case that happens in production, when
    launches start failing because the machine is already loaded.
    """
    from camoufox.async_api import AsyncCamoufox

    with pytest.raises(BaseException):
        async with AsyncCamoufox(
            executable_path=str(binary),
            headless=True,
            timeout=1,
            i_know_what_im_doing=True,
        ):
            pass
    leak_check.assert_clean()


async def test_close_failing_still_tears_down(binary, leak_check):
    """The other half of #82: close() raising must not skip the teardown.

    Simulated by killing the browser process out from under the wrapper, which
    is what a crash looks like from the outside.
    """
    from camoufox.async_api import AsyncCamoufox

    psutil = pytest.importorskip("psutil")
    try:
        async with AsyncCamoufox(executable_path=str(binary), headless=True,
                                 i_know_what_im_doing=True) as browser:
            page = await (await browser.new_context()).new_page()
            await page.goto("about:blank")
            for child in psutil.Process().children(recursive=True):
                if "camoufox" in child.name().lower() or "firefox" in child.name().lower():
                    child.kill()
            await asyncio.sleep(1.0)
    except BaseException:
        # Whether the wrapper re-raises is not what is under test; that the
        # session is gone afterwards is.
        pass
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# scaling -- the shape a real leak actually has
# ---------------------------------------------------------------------------
#
# "Did we return exactly to baseline" is the wrong question. A launch legitimately
# leaves a socket or two in TIME_WAIT, and asserting on that produces a flaky
# test that gets switched off. A leak has a different signature: the cost is
# paid *per round*, so ten rounds cost ten times one round. These tests measure
# the slope, not the intercept.


async def test_descriptor_use_does_not_scale_with_rounds(binary, psutil_mod):
    """Two rounds versus six. A per-round descriptor leak shows up as a slope.

    This is the failure that ends a long-running scraper: every job leaks one
    socket, nothing looks wrong for hours, and then everything fails at once
    with EMFILE.
    """
    from conftest import fd_count, settle

    async def rounds(count: int) -> int:
        settle(psutil_mod, timeout=15)
        start = fd_count()
        for _ in range(count):
            await _launch_and_close(binary)
        settle(psutil_mod, timeout=15)
        return fd_count() - start

    small = await rounds(2)
    large = await rounds(6)

    # A clean implementation gives roughly the same small delta either way. A
    # per-round leak of even one descriptor gives large - small >= 4.
    assert large <= max(small, 0) + 4, (
        f"file descriptors scale with launch count: 2 rounds cost {small}, "
        f"6 rounds cost {large}. That is a per-round leak of about "
        f"{(large - small) / 4:.1f} descriptor(s)."
    )


async def test_rss_does_not_climb_across_rounds(binary, psutil_mod, request):
    """A trend check, not a threshold.

    Peak RSS never falls -- getrusage reports a high-water mark -- so this looks
    at growth *after* the first round has paid for imports, the driver, and the
    Playwright client. If rounds two onward keep adding megabytes, something in
    this process is retaining per-launch state.

    Scope: our own process. A leak inside Gecko's heap is not visible from here
    and this suite does not claim to find one.
    """
    from conftest import settle

    rounds = max(3, request.config.getoption("--rounds"))
    samples = []
    for _ in range(rounds):
        await _launch_and_close(binary)
        settle(psutil_mod, timeout=10)
        samples.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

    growth_kb = samples[-1] - samples[0]
    per_round_kb = growth_kb / max(1, len(samples) - 1)
    assert per_round_kb < 25_000, (
        f"peak RSS grew {growth_kb / 1024:.1f} MB across {len(samples)} rounds "
        f"({per_round_kb / 1024:.1f} MB per round). Samples (KB): {samples}"
    )


async def test_no_stale_x11_artifacts_after_virtual_display(leak_check):
    """The rule from PR #652: SIGKILL, reap, then unlink the lock and socket.

    A leftover /tmp/.X{n}-lock blocks that display number for every later
    process on the machine, so this leaks across runs, not just within one.
    """
    if os.environ.get("CI_SKIP_VIRTUAL_DISPLAY"):
        pytest.skip("virtual display tests disabled for this run")
    from camoufox.virtdisplay import VirtualDisplay

    try:
        display = VirtualDisplay()
        number = display.get()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Xvfb unavailable: {exc}")

    assert number.startswith(":")
    index = number.lstrip(":")
    display.kill()

    assert not Path(f"/tmp/.X{index}-lock").exists(), (
        f"/tmp/.X{index}-lock survived kill(); it will block display :{index} for "
        "every later process on this machine"
    )
    assert not Path(f"/tmp/.X11-unix/X{index}").exists(), (
        f"/tmp/.X11-unix/X{index} survived kill()"
    )
    leak_check.assert_clean()


async def test_many_virtual_displays_are_unique_and_all_release(psutil_mod):
    """Displays are claimed atomically (issue #597) and all come back.

    The old lock-file scan handed the same number to several processes starting
    at once. This is the cheap version of that race: claim a batch, assert they
    are distinct, release them, assert nothing is left.
    """
    from camoufox.virtdisplay import VirtualDisplay

    displays = []
    try:
        for _ in range(8):
            display = VirtualDisplay()
            displays.append((display, display.get()))
    except Exception as exc:  # noqa: BLE001
        for display, _ in displays:
            display.kill()
        pytest.skip(f"Xvfb unavailable: {exc}")

    numbers = [n for _, n in displays]
    assert len(set(numbers)) == len(numbers), f"duplicate display numbers handed out: {numbers}"

    for display, _ in displays:
        display.kill()

    leftovers = [n for n in numbers if Path(f"/tmp/.X{n.lstrip(':')}-lock").exists()]
    assert not leftovers, f"lock files survived for {leftovers}"


async def test_cleanup_runs_even_when_xvfb_already_died(psutil_mod):
    """The crash path is the one where cleanup matters most.

    kill() used to gate its whole body on `self.proc.poll() is None` -- "is Xvfb
    still running". So a display whose Xvfb had already died was never cleaned
    up: /tmp/.X11-unix/X<n> was left behind, and self.proc stayed set.

    That is exactly backwards. A SIGKILLed Xvfb never gets the chance to remove
    its own socket, so the only time the socket survives is the time kill() was
    declining to do anything about it. Stranded sockets accumulate, and since
    -displayfd scans upward for a free number, each one pushes the next display
    higher until the host cannot allocate at all.
    """
    if os.environ.get("CI_SKIP_VIRTUAL_DISPLAY"):
        pytest.skip("virtual display tests disabled for this run")
    from camoufox.virtdisplay import VirtualDisplay

    try:
        display = VirtualDisplay()
        number = display.get().lstrip(":")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Xvfb unavailable: {exc}")

    # Kill it out from under the object, the way a crash or the OOM killer does.
    os.kill(display.proc.pid, signal.SIGKILL)
    await asyncio.sleep(1.5)
    display.proc.poll()  # reap, so poll() reports an exit status
    assert display.proc.poll() is not None, "Xvfb did not actually die"

    display.kill()

    survivors = [
        path for path in (f"/tmp/.X{number}-lock", f"/tmp/.X11-unix/X{number}")
        if Path(path).exists()
    ]
    for path in survivors:  # do not leave the machine worse than we found it
        try:
            os.unlink(path)
        except OSError:
            pass

    assert not survivors, (
        f"kill() left {survivors} behind after Xvfb had already died. Every crashed "
        f"browser strands display :{number} for the rest of the machine's life."
    )
    assert display.proc is None, "kill() did not mark the display as cleaned up"
