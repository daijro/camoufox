"""
Verifies the xvfb / virtual-display launch path.

Most users on Linux servers run Camoufox under Xvfb to avoid headless-mode
fingerprints. We exercise that path here by launching Xvfb ourselves and
pointing Camoufox at it via DISPLAY, rather than going through the
camoufox python wrapper's `headless="virtual"` API. The wrapper's
helper is a thin Xvfb subprocess + DISPLAY env wrapper; testing the
underlying combination directly catches regressions in either layer
and avoids coupling to pythonlib's install-path validation.

Tests skip cleanly when Xvfb isn't installed.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which("Xvfb") is None,
    reason="Xvfb not installed; cannot test virtual display path.",
)


def _free_display() -> int:
    """Find an unused X DISPLAY number."""
    for n in range(99, 200):
        sock_path = f"/tmp/.X11-unix/X{n}"
        lock_path = f"/tmp/.X{n}-lock"
        if not os.path.exists(sock_path) and not os.path.exists(lock_path):
            return n
    raise RuntimeError("no free X DISPLAY in range :99-:199")


@asynccontextmanager
async def _xvfb(width: int = 1280, height: int = 720, depth: int = 24) -> AsyncIterator[str]:
    """Spawn Xvfb, yield the DISPLAY string, tear down on exit."""
    display_num = _free_display()
    display = f":{display_num}"
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", f"{width}x{height}x{depth}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Xvfb takes ~100ms to create its socket; wait for it.
    deadline = time.monotonic() + 5.0
    sock_path = f"/tmp/.X11-unix/X{display_num}"
    while time.monotonic() < deadline:
        if os.path.exists(sock_path):
            break
        await asyncio.sleep(0.05)
    else:
        proc.kill()
        raise RuntimeError(f"Xvfb did not create {sock_path} within 5s")
    try:
        yield display
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.timeout(60)
async def test_camoufox_launches_under_xvfb_in_headed_mode(camoufox_binary: str) -> None:
    """Headed Camoufox under Xvfb should launch and navigate normally."""
    from playwright.async_api import async_playwright

    async with _xvfb() as display:
        env = {**os.environ, "DISPLAY": display}
        async with async_playwright() as p:
            browser = await p.firefox.launch(
                executable_path=camoufox_binary,
                headless=False,
                env=env,
            )
            page = await browser.new_page()
            await page.goto("about:blank")
            assert await page.title() == ""
            await browser.close()


@pytest.mark.timeout(60)
async def test_xvfb_launch_does_not_advertise_headless(camoufox_binary: str) -> None:
    """The whole point of running under Xvfb: not advertising headless mode."""
    from playwright.async_api import async_playwright

    async with _xvfb() as display:
        env = {**os.environ, "DISPLAY": display}
        async with async_playwright() as p:
            browser = await p.firefox.launch(
                executable_path=camoufox_binary,
                headless=False,
                env=env,
            )
            page = await browser.new_page()
            await page.goto("about:blank")
            ua = await page.evaluate("() => navigator.userAgent")
            assert "Headless" not in ua, f"UA leaks headless mode: {ua}"
            wd = await page.evaluate("() => navigator.webdriver")
            assert not wd, f"navigator.webdriver leaked: {wd!r}"
            await browser.close()
