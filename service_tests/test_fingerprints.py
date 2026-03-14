"""
Service tests for cloverlabs-camoufox.
Validates that fingerprints are unique per context and that contexts are isolated.
"""

import asyncio
import logging
import pytest
from camoufox.async_api import AsyncCamoufox, AsyncNewContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio(loop_scope="function")

N_CONTEXTS = 5

FINGERPRINT_SELECTOR = "#fingerprint-data > div.fingerprint-header-container > div > div.ellipsis-all"


def _parse_ff_version(specifier: str | None) -> int | None:
    if not specifier:
        return None
    for part in specifier.split("/"):
        try:
            return int(part.split(".")[0])
        except ValueError:
            continue
    return None


async def _collect_fingerprint(browser, index: int) -> dict:
    log.info("[context %d] Creating context...", index)
    context = await AsyncNewContext(browser)
    page = await context.new_page()

    log.info("[context %d] Navigating to CreepJS...", index)
    await page.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded", timeout=60_000)

    log.info("[context %d] Waiting 5s for CreepJS to compute...", index)
    await asyncio.sleep(5)

    creepjs_id = (await page.inner_text(FINGERPRINT_SELECTOR)).strip()
    log.info("[context %d] CreepJS fingerprint ID: %s", index, creepjs_id)

    fp = {
        "creepjs_id": creepjs_id,
        "user_agent": await page.evaluate("navigator.userAgent"),
        "platform": await page.evaluate("navigator.platform"),
        "hardware_concurrency": await page.evaluate("navigator.hardwareConcurrency"),
        "screen_width": await page.evaluate("screen.width"),
        "screen_height": await page.evaluate("screen.height"),
        "webgl_vendor": await page.evaluate("""() => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
            if (!ctx) return null;
            const ext = ctx.getExtension('WEBGL_debug_renderer_info');
            return ext ? ctx.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null;
        }"""),
        "webgl_renderer": await page.evaluate("""() => {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
            if (!ctx) return null;
            const ext = ctx.getExtension('WEBGL_debug_renderer_info');
            return ext ? ctx.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
        }"""),
    }

    await context.close()
    log.info("[context %d] Closed.", index)
    return fp


async def test_unique_fingerprints_per_context(camoufox_version, headful):
    """Each context must produce a unique CreepJS fingerprint ID."""
    ff_version = _parse_ff_version(camoufox_version)
    kwargs = {"headless": not headful}
    if ff_version:
        kwargs["ff_version"] = ff_version

    log.info("=== Launching browser, opening %d contexts in parallel ===", N_CONTEXTS)
    async with AsyncCamoufox(**kwargs) as browser:
        fingerprints = await asyncio.gather(
            *[_collect_fingerprint(browser, i) for i in range(N_CONTEXTS)]
        )

    log.info("--- Fingerprint summary ---")
    for i, fp in enumerate(fingerprints):
        log.info("  [%d] CreepJS ID=%s | UA=%s | platform=%s | screen=%sx%s | webgl=%s / %s",
                 i, fp["creepjs_id"], fp["user_agent"], fp["platform"],
                 fp["screen_width"], fp["screen_height"],
                 fp["webgl_vendor"], fp["webgl_renderer"])

    creepjs_ids = [fp["creepjs_id"] for fp in fingerprints]
    assert len(set(creepjs_ids)) == N_CONTEXTS, (
        f"Expected all {N_CONTEXTS} CreepJS IDs to be unique, got: {creepjs_ids}"
    )
    log.info("PASS: all CreepJS fingerprint IDs are unique")


async def test_contexts_are_isolated(camoufox_version, headful):
    """localStorage and cookies must not bleed between contexts."""
    ff_version = _parse_ff_version(camoufox_version)
    kwargs = {"headless": not headful}
    if ff_version:
        kwargs["ff_version"] = ff_version

    log.info("=== test_contexts_are_isolated: creating 2 contexts ===")
    async with AsyncCamoufox(**kwargs) as browser:
        ctx1 = await AsyncNewContext(browser)
        ctx2 = await AsyncNewContext(browser)

        page1 = await ctx1.new_page()
        page2 = await ctx2.new_page()

        await asyncio.gather(
            page1.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded"),
            page2.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded"),
        )

        log.info("Writing localStorage key in context 1...")
        await page1.evaluate("localStorage.setItem('camoufox_test', 'secret')")
        value_in_ctx2 = await page2.evaluate("localStorage.getItem('camoufox_test')")
        log.info("localStorage 'camoufox_test' in context 2: %s", value_in_ctx2)
        assert value_in_ctx2 is None, (
            f"localStorage leaked from context 1 to context 2: got '{value_in_ctx2}'"
        )
        log.info("PASS: localStorage is isolated")

        log.info("Setting cookie in context 1...")
        await ctx1.add_cookies([{
            "name": "camoufox_cookie",
            "value": "ctx1_value",
            "domain": "abrahamjuliot.github.io",
            "path": "/",
        }])
        cookies_in_ctx2 = await ctx2.cookies("https://abrahamjuliot.github.io/creepjs/")
        cookie_names = [c["name"] for c in cookies_in_ctx2]
        log.info("Cookies visible in context 2: %s", cookie_names)
        assert "camoufox_cookie" not in cookie_names, (
            f"Cookie leaked from context 1 to context 2: {cookies_in_ctx2}"
        )
        log.info("PASS: cookies are isolated")

        await ctx1.close()
        await ctx2.close()

    log.info("=== test_contexts_are_isolated complete ===")
