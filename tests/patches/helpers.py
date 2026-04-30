"""
Shared helpers for patch verification tests.

Run tests from dvsa-bot to get the right venv:
    cd ~/20tech/drivingtest/dvsa-bot
    uv run python ~/20tech/oss/camoufox/tests/patches/<test>.py
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, Optional


MAX_PRESET_ATTEMPTS = 15


@asynccontextmanager
async def launch_camoufox(
    os: str = "macos",
    headless: bool = True,
    max_attempts: int = MAX_PRESET_ATTEMPTS,
):
    """
    Launch Camoufox with a random preset, retrying on WebGL mismatches.

    Yields (page, fingerprint_config) — the config dict lets tests check
    what values were sent to the browser.

    About half of get_random_preset() calls produce a WebGL vendor/renderer
    combo that doesn't exist in the sample data. This wrapper retries
    transparently so every test doesn't need its own retry loop.
    """
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    last_error: Optional[Exception] = None
    for attempt in range(max_attempts):
        preset = get_random_preset(os=os)
        fp = generate_context_fingerprint(preset=preset)
        try:
            async with AsyncCamoufox(
                fingerprint_preset=fp["preset"],
                headless=headless,
                os=os,
            ) as browser:
                context = await browser.new_context(**fp["context_options"])
                await context.add_init_script(fp["init_script"])
                page = await context.new_page()
                await page.goto("about:blank")
                yield page, fp["config"]
                return
        except ValueError as e:
            if "WebGL" in str(e):
                last_error = e
                continue
            raise

    raise RuntimeError(
        f"Could not find a valid preset after {max_attempts} attempts"
    ) from last_error
