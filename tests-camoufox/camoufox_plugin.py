"""
Camoufox pytest plugin.

Loaded via `pytest -p camoufox_plugin` when running the upstream
microsoft/playwright-python test suite against a Camoufox binary.

Job:
  1. Inject CAMOUFOX_EXECUTABLE_PATH into the upstream `launch_arguments`
     fixture so all `firefox.launch(...)` calls use the Camoufox binary.
  2. Skip tests that explicitly need a real X server (`headless=False`)
     when DISPLAY is unset.
  3. Provide hooks for Camoufox-specific stealth behaviour to be tolerated
     by upstream assertions (e.g. UA contains "Camoufox" not "Firefox").

Anything that should *only* run against Camoufox lives in
`tests-camoufox/test_*.py`, not here.
"""

from __future__ import annotations

import os
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# 1. Force every firefox.launch / launch_persistent_context to use the
#    Camoufox binary by monkey-patching at the BrowserType layer.
#
# We can't do this with a pytest fixture: upstream's
# tests/async/conftest.py defines its own session-scoped `launch_arguments`,
# and conftest fixtures take precedence over plugin fixtures at the same
# scope. Monkey-patching at pytest_configure time is the only reliable way
# to ensure *every* launch call (whether via the fixture or directly inside
# a test) uses the Camoufox binary.
# ---------------------------------------------------------------------------


def pytest_configure(config: "pytest.Config") -> None:
    exec_path = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
    if not exec_path:
        return  # nothing to inject; treat upstream binary as the SUT
    abs_path = os.path.abspath(exec_path)

    from playwright._impl import _browser_type

    BrowserType = _browser_type.BrowserType

    def _inject(kwargs: dict, browser_type: Any) -> dict:
        # Only inject for firefox; chromium/webkit calls pass through.
        if getattr(browser_type, "name", None) != "firefox":
            return kwargs
        # The async_api wrapper always forwards `executablePath=None` (the
        # default) when not supplied, so checking key presence isn't enough —
        # only inject when the caller did not actually provide a value.
        if not kwargs.get("executablePath") and not kwargs.get("executable_path"):
            kwargs = {**kwargs, "executablePath": abs_path}
        return kwargs

    orig_launch = BrowserType.launch
    orig_persistent = BrowserType.launch_persistent_context

    async def patched_launch(self: Any, **kwargs: Any) -> Any:
        return await orig_launch(self, **_inject(kwargs, self))

    async def patched_persistent(self: Any, userDataDir: Any, **kwargs: Any) -> Any:
        return await orig_persistent(self, userDataDir, **_inject(kwargs, self))

    BrowserType.launch = patched_launch  # type: ignore[assignment]
    BrowserType.launch_persistent_context = patched_persistent  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 2. Skip tests that force headless=False when there's no DISPLAY.
#
# Upstream's `test_headful.py` (and a few one-offs in `test_browsercontext.py`)
# call `browser_type.launch(headless=False, ...)` directly. Without an X server
# they all fail at process spawn — that's an environment shortcoming, not a
# Camoufox bug. Skip them cleanly.
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config: "pytest.Config", items: list) -> None:
    if os.environ.get("DISPLAY"):
        return
    skip_marker = pytest.mark.skip(
        reason="No DISPLAY — test forces headless=False. Run under xvfb-run "
        "or set DISPLAY to enable."
    )
    headful_modules = {"test_headful"}
    for item in items:
        module_name = item.module.__name__.rsplit(".", 1)[-1]
        if module_name in headful_modules:
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# 3. Stealth-aware tolerances for upstream assertions.
#
# Some upstream assertions hard-code "Firefox" in the User-Agent string. The
# Camoufox UA is "...Camoufox/<version>" by default. We *do not* mutate
# upstream test code; instead this hook is for places where upstream
# explicitly exposes a parametrised hook.
#
# Currently empty — left as the place to put future tolerances if/when we
# decide to stop monkey-patching upstream tests directly.
# ---------------------------------------------------------------------------
