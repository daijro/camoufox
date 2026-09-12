"""Kill things badly and check what survives.

The tests in test_no_leaks.py cover the happy path: open a browser, close it,
nothing left behind. This file covers the other one -- the browser dies, the X
server disappears, a content process is OOM-killed, the driver is reaped -- and
asks two questions about each:

  1. **Does it hang?** A crashed browser that makes close() wait forever wedges
     a long-running scraper at 0% CPU with no error and no diagnostic. Every
     teardown here runs under a deadline, so a hang fails with a name attached
     rather than sitting until the CI runner's timeout.

  2. **Does it leak?** After the dust settles: no process this test started is
     still alive, no stale X11 lock is blocking a display number for the rest of
     the machine, and file descriptors have come back.

And a third, implicitly: **can you carry on?** Several tests launch a fresh
browser after the crash, because the failure that really hurts is the one that
poisons the machine -- a leftover /tmp/.X11-unix socket that makes every later
launch pick a different display, or a process group that never gets reaped.

These are slow: each test launches at least one real browser. That is the cost
of testing what actually happens rather than what a mock says happens.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from _chaos import (
    BROWSER,
    DRIVER,
    FORKSERVER,
    RDD,
    SOCKET_PROCESS,
    WEB_CONTENT,
    WEB_EXTENSIONS,
    driver_process,
    XVFB,
    bounded,
    close_bounded,
    descendants,
    sigkill,
    wait_for_process,
    x11_artifacts_for,
)

pytestmark = pytest.mark.asyncio

# Generous, because a crashed browser's teardown legitimately involves waiting
# for a driver round-trip to time out. Tight enough that a real hang is caught.
TEARDOWN_DEADLINE = 90.0


async def open_browser(binary, *, headless=True, **kwargs):
    """Open a browser, returning the context manager so teardown can be timed.

    `headless` is a real parameter rather than a hardcoded True: the virtual
    display tests pass headless="virtual", and splatting that through **kwargs
    made AsyncCamoufox raise "got multiple values for keyword argument
    'headless'" -- so the two X-server tests errored during setup and never
    exercised anything.
    """
    from camoufox.async_api import AsyncCamoufox

    manager = AsyncCamoufox(
        executable_path=str(binary), headless=headless, i_know_what_im_doing=True, **kwargs
    )
    return manager, await manager.__aenter__()


async def teardown(manager, what):
    """__aexit__ under a deadline, tolerating the exception a crash produces."""
    async def run():
        try:
            await manager.__aexit__(None, None, None)
        except BaseException:
            # A dead browser makes close() raise. That is correct; the rule from
            # issue #82 is that teardown still runs, which leak_check verifies.
            pass

    return await bounded(run(), TEARDOWN_DEADLINE, what)


async def a_page(browser):
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("about:blank")
    return context, page


# ---------------------------------------------------------------------------
# the browser process dies
# ---------------------------------------------------------------------------


async def test_browser_sigkill_does_not_hang_or_leak(binary, psutil_mod, leak_check):
    """The OOM killer's favourite target.

    Everything below camoufox-bin -- Socket Process, forkserver, content -- must
    go with it, and the driver must not be left holding a connection to a
    process that no longer exists.
    """
    manager, browser = await open_browser(binary)
    await a_page(browser)
    killed = sigkill(psutil_mod, BROWSER)
    assert killed, "no browser process to kill"

    await teardown(manager, f"teardown after SIGKILL of {killed[0]}")
    leak_check.assert_clean()


async def test_browser_sigkill_with_many_contexts_open(binary, psutil_mod, leak_check):
    """Connections opened before the crash must not outlive it."""
    manager, browser = await open_browser(binary)
    for _ in range(4):
        await a_page(browser)
    sigkill(psutil_mod, BROWSER)
    await teardown(manager, "teardown after SIGKILL with 4 contexts open")
    leak_check.assert_clean()


async def test_a_fresh_browser_launches_after_a_crash(binary, psutil_mod, leak_check):
    """The crash must not poison the machine for the next launch."""
    manager, browser = await open_browser(binary)
    await a_page(browser)
    sigkill(psutil_mod, BROWSER)
    await teardown(manager, "teardown after crash")

    manager2, browser2 = await open_browser(binary)
    _, page = await a_page(browser2)
    assert await page.evaluate("1 + 1") == 2, "a browser launched after a crash is not usable"
    await teardown(manager2, "teardown of the recovery browser")
    leak_check.assert_clean()


async def test_repeated_crashes_do_not_accumulate(binary, psutil_mod, leak_check):
    """Three crash-and-recover cycles must cost what one costs."""
    for _ in range(3):
        manager, browser = await open_browser(binary)
        await a_page(browser)
        sigkill(psutil_mod, BROWSER)
        await teardown(manager, "teardown after crash")
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# a child of the browser dies
# ---------------------------------------------------------------------------


async def test_content_process_sigkill_is_survivable(binary, psutil_mod, leak_check):
    """A content process is the one Firefox is built to lose.

    Killing it should not take down the browser, and the replacement must not
    leave the old one's descriptors behind.
    """
    manager, browser = await open_browser(binary)
    context, page = await a_page(browser)
    killed = sigkill(psutil_mod, WEB_CONTENT)
    assert killed, "no content process to kill"

    # The browser should still be there. Whether *this* page recovers is
    # Firefox's business; that the browser survives is what we assert.
    await asyncio.sleep(2)
    alive = descendants(psutil_mod, name=BROWSER)
    assert alive, f"killing {killed[0]} took the whole browser down with it"

    await teardown(manager, "teardown after a content-process crash")
    leak_check.assert_clean()


async def test_one_contexts_content_crash_leaves_the_other_alone(binary, psutil_mod, leak_check):
    """Two contexts, one loses its content process. The other must keep working."""
    manager, browser = await open_browser(binary)
    ctx_a, page_a = await a_page(browser)
    ctx_b, page_b = await a_page(browser)

    before = len(descendants(psutil_mod, name=WEB_CONTENT))
    sigkill(psutil_mod, WEB_CONTENT)
    await asyncio.sleep(2)

    surviving = await bounded(page_b.evaluate("1 + 1"), 30, "evaluate in the untouched context")
    assert surviving == 2, (
        "killing one context's content process broke a different context. Contexts "
        "are meant to be isolated from each other's failures."
    )
    assert before >= 1

    await teardown(manager, "teardown after one context lost its content process")
    leak_check.assert_clean()


async def test_socket_process_sigkill_does_not_hang(binary, psutil_mod, leak_check):
    """Firefox's networking process. Losing it must not wedge teardown."""
    manager, browser = await open_browser(binary)
    await a_page(browser)
    sigkill(psutil_mod, SOCKET_PROCESS)
    await teardown(manager, "teardown after the socket process was killed")
    leak_check.assert_clean()


async def test_forkserver_sigkill_does_not_hang(binary, psutil_mod, leak_check):
    """The forkserver spawns content processes; losing it is a nastier failure."""
    manager, browser = await open_browser(binary)
    await a_page(browser)
    sigkill(psutil_mod, FORKSERVER)
    await teardown(manager, "teardown after the forkserver was killed")
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# the driver dies
# ---------------------------------------------------------------------------


async def test_driver_sigkill_does_not_orphan_the_browser(binary, psutil_mod, leak_check):
    """Playwright's node driver is the browser's parent.

    Kill it and the browser is reparented to init, out of reach of anything that
    would normally close it. If nothing notices, that browser runs forever.
    """
    manager, browser = await open_browser(binary)
    await a_page(browser)

    driver = driver_process(psutil_mod)
    if driver is None:
        pytest.skip("the browser was launched directly; there is no separate driver to kill")
    try:
        driver.kill()
    except psutil_mod.NoSuchProcess:
        pass
    psutil_mod.wait_procs([driver], timeout=15)

    await teardown(manager, f"teardown after killing the driver ({driver.pid})")
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# the X server goes away
# ---------------------------------------------------------------------------


def _virtual_display_supported() -> bool:
    from shutil import which

    return which("Xvfb") is not None


async def test_xvfb_sigkill_under_a_virtual_display(binary, psutil_mod, leak_check):
    """The X server disappears from under a running browser.

    A browser whose display vanishes can legitimately die. What it must not do
    is hang, and what must not survive is the display's lock file -- that blocks
    the number for every later process on the machine, not just this one.
    """
    if not _virtual_display_supported():
        pytest.skip("Xvfb is not installed")

    manager, browser = await open_browser(binary, headless="virtual")
    await a_page(browser)

    xvfbs = wait_for_process(psutil_mod, XVFB)
    display = None
    for proc in xvfbs:
        for arg in proc.cmdline():
            if arg.startswith(":") and arg[1:].isdigit():
                display = arg
    sigkill(psutil_mod, XVFB)

    await teardown(manager, "teardown after the X server was killed")

    if display:
        for path in x11_artifacts_for(display):
            assert not Path(path).exists(), (
                f"{path} survived the X server being killed. It blocks display {display} "
                "for every later process on this machine, not just this test."
            )
    leak_check.assert_clean()


async def test_browser_crash_under_a_virtual_display_does_not_leak_xvfb(binary, psutil_mod, leak_check):
    """The other order: the browser dies, the X server it was using must not stay.

    This is the pairing that leaks in practice -- teardown runs on the browser's
    close path, so a browser that never reaches it can strand its Xvfb.
    """
    if not _virtual_display_supported():
        pytest.skip("Xvfb is not installed")

    manager, browser = await open_browser(binary, headless="virtual")
    await a_page(browser)
    wait_for_process(psutil_mod, XVFB)
    sigkill(psutil_mod, BROWSER)

    await teardown(manager, "teardown after the browser crashed under a virtual display")

    stranded = descendants(psutil_mod, name=XVFB)
    assert not stranded, (
        f"{len(stranded)} Xvfb process(es) outlived the browser they were started for. "
        "Every crashed browser would strand one, and they accumulate until the "
        "machine runs out of displays."
    )
    leak_check.assert_clean()


async def test_a_stale_x11_lock_does_not_block_the_next_display(psutil_mod):
    """Recovery from someone else's mess.

    A machine that has been killing browsers may have stale lock files lying
    around. Xvfb's -displayfd scans upward for a free number, so allocation must
    still succeed -- if it did not, one bad crash would poison the host.
    """
    if not _virtual_display_supported():
        pytest.skip("Xvfb is not installed")

    from camoufox.virtdisplay import VirtualDisplay

    litter = Path("/tmp/.X77-lock")
    created = not litter.exists()
    if created:
        litter.write_text("99999\n")
    try:
        display = VirtualDisplay()
        number = display.get()
        assert number.startswith(":")
        display.kill()
    finally:
        if created and litter.exists():
            litter.unlink()


# ---------------------------------------------------------------------------
# abandonment
# ---------------------------------------------------------------------------


async def test_an_exception_inside_the_context_manager_still_tears_down(binary, leak_check):
    """The user's code raises. Teardown is not optional because of that."""
    from camoufox.async_api import AsyncCamoufox

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        async with AsyncCamoufox(
            executable_path=str(binary), headless=True, i_know_what_im_doing=True
        ) as browser:
            await a_page(browser)
            raise Boom("something in the caller's code went wrong")

    leak_check.assert_clean()


async def test_killing_the_browser_mid_navigation(binary, psutil_mod, leak_check):
    """Crash while a page is in flight, not while it is idle.

    An in-flight navigation has a pending protocol call waiting for a reply that
    is never coming -- the classic shape for an unbounded await.
    """
    manager, browser = await open_browser(binary)
    context = await browser.new_context()
    page = await context.new_page()

    async def navigate():
        try:
            await page.goto("http://127.0.0.1:9/slow", timeout=20_000)
        except BaseException:
            pass

    task = asyncio.create_task(navigate())
    await asyncio.sleep(0.5)
    sigkill(psutil_mod, BROWSER)
    await bounded(task, 45, "an in-flight navigation after the browser was killed")

    await teardown(manager, "teardown after a crash mid-navigation")
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# frozen, not dead
# ---------------------------------------------------------------------------


async def test_a_frozen_browser_does_not_hang_teardown_forever(binary, psutil_mod, leak_check):
    """SIGSTOP, not SIGKILL. The nastier failure of the two.

    A killed process closes its sockets, so the driver notices immediately. A
    *stopped* one holds every connection open and answers nothing -- which is
    exactly the shape that produces an unbounded await, and exactly what a
    machine under heavy swap or a paused container looks like.

    The rule is not that teardown succeeds. It is that teardown *returns*.
    """
    import signal

    manager, browser = await open_browser(binary)
    await a_page(browser)

    frozen = wait_for_process(psutil_mod, BROWSER)
    for proc in frozen:
        proc.send_signal(signal.SIGSTOP)
    try:
        await teardown(manager, "teardown while the browser is SIGSTOPped")
    finally:
        # Always thaw, or the leak check finds a process that cannot be reaped
        # and the machine keeps a stopped browser forever.
        for proc in frozen:
            try:
                proc.send_signal(signal.SIGCONT)
                proc.kill()
            except Exception:
                pass
        psutil_mod.wait_procs(frozen, timeout=15)

    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# the remaining child process types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("victim", [RDD, WEB_EXTENSIONS])
async def test_auxiliary_process_sigkill_does_not_hang_or_leak(binary, psutil_mod, leak_check, victim):
    """The processes nobody thinks about until one of them is missing.

    RDD decodes media; WebExtensions hosts uBO. Neither is on the critical path
    for a page load, so losing one should be survivable -- but both are children
    of the forkserver, and a teardown that waits on a dead child hangs the same
    way whichever child it was.
    """
    manager, browser = await open_browser(binary)
    await a_page(browser)
    try:
        sigkill(psutil_mod, victim, timeout=20)
    except AssertionError:
        pytest.skip(f"no {victim} process in this build's tree")
    await teardown(manager, f"teardown after {victim} was killed")
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# crashing at awkward moments
# ---------------------------------------------------------------------------


async def test_crash_while_a_context_is_being_created(binary, psutil_mod, leak_check):
    """The race: kill the browser during new_context(), not after it.

    Half-built objects are where teardown paths tend to have gaps, because the
    cleanup code assumes the thing it is cleaning up finished being made.
    """
    manager, browser = await open_browser(binary)

    async def make_contexts():
        try:
            for _ in range(8):
                await browser.new_context()
        except BaseException:
            pass

    task = asyncio.create_task(make_contexts())
    await asyncio.sleep(0.3)
    sigkill(psutil_mod, BROWSER)
    await bounded(task, 45, "new_context() while the browser was being killed")

    await teardown(manager, "teardown after a crash mid new_context()")
    leak_check.assert_clean()


async def test_one_of_two_browsers_crashing_leaves_the_other_usable(binary, psutil_mod, leak_check):
    """Two browsers, one dies. The survivor must not be collateral damage.

    They share this process's Playwright session, so a teardown path that reset
    something session-wide would take both down -- and that would only ever show
    up when more than one browser is open.
    """
    manager_a, browser_a = await open_browser(binary)
    _, page_a = await a_page(browser_a)
    manager_b, browser_b = await open_browser(binary)
    _, page_b = await a_page(browser_b)

    # Kill only the newest browser process, so exactly one dies.
    victims = wait_for_process(psutil_mod, BROWSER)
    assert len(victims) >= 2, f"expected two browsers, saw {len(victims)}"
    newest = max(victims, key=lambda p: p.create_time())
    newest.kill()
    psutil_mod.wait_procs([newest], timeout=15)
    await asyncio.sleep(2)

    survivor = await bounded(page_a.evaluate("1 + 1"), 30, "evaluate in the surviving browser")
    assert survivor == 2, "killing one browser broke a second, independent browser"

    await teardown(manager_b, "teardown of the crashed browser")
    await teardown(manager_a, "teardown of the surviving browser")
    leak_check.assert_clean()


# ---------------------------------------------------------------------------
# a content process dies on its own  (daijro/camoufox#762)
# ---------------------------------------------------------------------------
#
# #762: with uBlock Origin excluded, an ad-heavy page grows its content process
# to ~15 GB and the tab dies. The parent stays flat at 479 MB throughout, so the
# failure is contained to one content process -- and Playwright surfaces it as
# `Target crashed` on the *next* call.
#
# That is a different shape from the kills above, which are inflicted from
# outside. Here the browser loses a child by itself, with a healthy parent, and
# the questions are about the aftermath: is the crash observable or silent, do
# later calls fail or hang, can the wreckage still be closed, and does anything
# accumulate when it happens over and over -- which for a scraper working
# through a list of ad-heavy pages, it will.
#
# Induction is a SIGKILL of the content process rather than an actual OOM. The
# end state is the same one #762 lands in (the content process is gone, the
# parent is fine) and it is deterministic, instant, and does not require
# allocating 15 GB on a CI runner. What is NOT claimed here is a reproduction of
# the runaway growth itself; that needs the real page.


async def _content_crash(psutil_mod, browser):
    """Take out one content process the way an OOM would."""
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("about:blank")
    sigkill(psutil_mod, WEB_CONTENT)
    return context, page


async def test_a_content_crash_is_observable_not_silent(binary, psutil_mod, leak_check):
    """page.on("crash") must fire.

    #762's reporter only learned the tab had died because a later call raised.
    A crash that is silent until you happen to touch the page is a crash a
    long-running job cannot react to -- it just keeps working with a dead tab.
    """
    manager, browser = await open_browser(binary)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("about:blank")

    crashed = asyncio.Event()
    page.on("crash", lambda _: crashed.set())

    sigkill(psutil_mod, WEB_CONTENT)
    fired = await bounded(crashed.wait(), 60, 'the page "crash" event')
    assert fired is not None, (
        'the page "crash" event never fired after its content process died. The '
        "failure is then invisible until something else happens to touch the page."
    )

    await teardown(manager, "teardown after an observed content crash")
    leak_check.assert_clean()


async def test_calls_after_a_content_crash_fail_rather_than_hang(binary, psutil_mod, leak_check):
    """`Target crashed` is the right answer. Waiting forever is not."""
    manager, browser = await open_browser(binary)
    context, page = await _content_crash(psutil_mod, browser)

    async def touch():
        try:
            await page.evaluate("1 + 1")
            return "returned"
        except BaseException as exc:
            return type(exc).__name__

    outcome = await bounded(touch(), 60, "a call on a page whose content process died")
    assert outcome is not None, "calling into a crashed page hung instead of failing"

    await teardown(manager, "teardown after calling into a crashed page")
    leak_check.assert_clean()


async def test_a_crashed_page_can_still_be_closed(binary, psutil_mod, leak_check):
    """Closing the wreckage must work, or every crashed tab is a permanent leak."""
    manager, browser = await open_browser(binary)
    context, page = await _content_crash(psutil_mod, browser)

    await bounded(close_bounded(context, 60, "context.close()"), 70, "closing a crashed context")
    await teardown(manager, "teardown after closing a crashed context")
    leak_check.assert_clean()


async def test_a_new_page_works_after_a_content_crash(binary, psutil_mod, leak_check):
    """One dead tab must not end the browser.

    #762 reports the parent is unaffected, so the browser should still be able
    to serve a fresh page -- which is what a scraper would do next.
    """
    manager, browser = await open_browser(binary)
    context, _ = await _content_crash(psutil_mod, browser)
    await asyncio.sleep(2)

    fresh_ctx = await browser.new_context()
    fresh = await fresh_ctx.new_page()
    await fresh.goto("about:blank")
    assert await bounded(fresh.evaluate("1 + 1"), 30, "evaluate in a page opened after a crash") == 2

    await teardown(manager, "teardown after recovering from a content crash")
    leak_check.assert_clean()


async def test_repeated_content_crashes_do_not_accumulate(binary, psutil_mod, leak_check):
    """The leak-shaped question #762 implies.

    A scraper working through ad-heavy pages will hit this repeatedly. If each
    dead tab strands a descriptor or a zombie, the job dies of exhaustion long
    before anyone connects it to the crashes.
    """
    manager, browser = await open_browser(binary)
    for _ in range(4):
        context, _ = await _content_crash(psutil_mod, browser)
        await asyncio.sleep(1)
        try:
            await bounded(close_bounded(context, 30, "context.close()"), 40, "closing a crashed context")
        except BaseException:
            pass
    await teardown(manager, "teardown after four content crashes")
    leak_check.assert_clean()


async def test_the_parent_stays_flat_across_content_crashes(binary, psutil_mod, leak_check):
    """#762 measured the parent at 479 MB, flat, while a child reached 15 GB.

    That containment is the property worth pinning. If a dying content process
    dragged the parent up with it, one bad page would take out every other tab
    in the browser rather than just its own.
    """
    manager, browser = await open_browser(binary)
    parents = wait_for_process(psutil_mod, BROWSER)
    parent = parents[0]
    baseline = parent.memory_info().rss

    for _ in range(3):
        context, _ = await _content_crash(psutil_mod, browser)
        await asyncio.sleep(1.5)
        try:
            await bounded(close_bounded(context, 30, "context.close()"), 40, "close")
        except BaseException:
            pass

    try:
        after = parent.memory_info().rss
    except psutil_mod.NoSuchProcess:
        raise AssertionError(
            "the parent process died along with its content processes. #762's whole "
            "point is that the parent is unaffected."
        ) from None

    growth_mb = (after - baseline) / (1024 * 1024)
    assert growth_mb < 400, (
        f"the browser parent grew {growth_mb:.0f} MB across three content-process "
        f"crashes ({baseline / 1e6:.0f} MB -> {after / 1e6:.0f} MB). A crashing child "
        "should not drag the parent up with it."
    )

    await teardown(manager, "teardown after measuring parent growth")
    leak_check.assert_clean()


async def test_teardown_is_clean_with_ublock_excluded(binary, psutil_mod, leak_check):
    """#762's one non-default argument, on the teardown path.

    Excluding a bundled addon changes how the profile is assembled, and the
    reported configuration is the one worth checking behaves like any other --
    including when the browser is killed under it.
    """
    from camoufox.addons import DefaultAddons

    manager, browser = await open_browser(binary, exclude_addons=[DefaultAddons.UBO])
    await a_page(browser)
    sigkill(psutil_mod, BROWSER)
    await teardown(manager, "teardown with uBlock Origin excluded")
    leak_check.assert_clean()
