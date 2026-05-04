"""
conftest for Camoufox-specific tests (the test_*.py files in this directory).

This conftest is for OUR tests only; the upstream Playwright suite is run
separately by run-tests.sh and gets the camoufox_plugin pytest plugin
instead.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio


def pytest_addoption(parser: "pytest.Parser") -> None:
    parser.addoption(
        "--headed",
        action="store_true",
        default=False,
        help="Run tests with a real browser window (default: headless).",
    )


def _binary_path() -> str:
    p = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
    if not p:
        pytest.skip("CAMOUFOX_EXECUTABLE_PATH not set")
    if not Path(p).is_file() or not os.access(p, os.X_OK):
        pytest.skip(f"CAMOUFOX_EXECUTABLE_PATH points to non-executable: {p}")
    return p


@pytest.fixture(scope="session")
def camoufox_binary() -> str:
    return _binary_path()


@pytest.fixture(scope="session")
def headless(pytestconfig: "pytest.Config") -> bool:
    return not bool(pytestconfig.getoption("--headed"))


@pytest_asyncio.fixture
async def camoufox_browser(camoufox_binary: str, headless: bool):
    """Plain Playwright firefox.launch() pointing at the Camoufox binary.

    This is the bare-bones launch — no Camoufox python wrapper. Use it
    when you want to test the binary's behaviour through the standard
    Playwright API. For tests that exercise the `pythonlib/` wrapper
    (CAMOU_CONFIG, AsyncNewContext, virtual display, etc.), launch
    through that wrapper directly inside the test.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            executable_path=camoufox_binary,
            headless=headless,
        )
        try:
            yield browser
        finally:
            await browser.close()
