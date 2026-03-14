"""
Service tests for cloverlabs-camoufox.
Validates that fingerprints are unique per context and that contexts are isolated.
"""

import logging
import time
import pytest
from camoufox.sync_api import Camoufox, NewContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

N_CONTEXTS = 5

WEBGL_VENDOR_JS = """() => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!ctx) return null;
    const ext = ctx.getExtension('WEBGL_debug_renderer_info');
    if (!ext) return null;
    return ctx.getParameter(ext.UNMASKED_VENDOR_WEBGL);
}"""

WEBGL_RENDERER_JS = """() => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!ctx) return null;
    const ext = ctx.getExtension('WEBGL_debug_renderer_info');
    if (!ext) return null;
    return ctx.getParameter(ext.UNMASKED_RENDERER_WEBGL);
}"""


@pytest.fixture(scope="session")
def browser(camoufox_version, headful):
    version_int = None
    if camoufox_version:
        for part in camoufox_version.split("/"):
            try:
                version_int = int(part.split(".")[0])
                break
            except ValueError:
                continue

    kwargs = {"headless": not headful}
    if version_int:
        kwargs["ff_version"] = version_int

    log.info("Launching browser (headless=%s, ff_version=%s)...", not headful, version_int)
    with Camoufox(**kwargs) as b:
        yield b
    log.info("Browser closed.")


def _collect_fingerprint(browser, index: int) -> dict:
    log.info("[context %d] Creating context...", index)
    context = NewContext(browser)
    page = context.new_page()

    log.info("[context %d] Navigating to CreepJS...", index)
    page.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded")

    log.info("[context %d] Waiting 5s for CreepJS to compute...", index)
    time.sleep(5)
    FINGERPRINT_SELECTOR = "#fingerprint-data > div.fingerprint-header-container > div > div.ellipsis-all"
    creepjs_id = page.inner_text(FINGERPRINT_SELECTOR).strip()
    log.info("[context %d] CreepJS fingerprint ID: %s", index, creepjs_id)

    log.info("[context %d] Collecting fingerprint properties...", index)
    fp = {
        "creepjs_id": creepjs_id,
        "user_agent": page.evaluate("navigator.userAgent"),
        "platform": page.evaluate("navigator.platform"),
        "hardware_concurrency": page.evaluate("navigator.hardwareConcurrency"),
        "screen_width": page.evaluate("screen.width"),
        "screen_height": page.evaluate("screen.height"),
        "webgl_vendor": page.evaluate(WEBGL_VENDOR_JS),
        "webgl_renderer": page.evaluate(WEBGL_RENDERER_JS),
    }

    log.info(
        "[context %d] UA=%s | platform=%s | screen=%sx%s | webgl=%s / %s",
        index,
        fp["user_agent"], fp["platform"],
        fp["screen_width"], fp["screen_height"],
        fp["webgl_vendor"], fp["webgl_renderer"],
    )

    context.close()
    log.info("[context %d] Closed.", index)
    return fp


def test_unique_fingerprints_per_context(browser):
    """Each context must receive a unique fingerprint."""
    log.info("=== test_unique_fingerprints_per_context: opening %d contexts ===", N_CONTEXTS)
    fingerprints = [_collect_fingerprint(browser, i) for i in range(N_CONTEXTS)]

    log.info("--- Fingerprint summary ---")
    for i, fp in enumerate(fingerprints):
        log.info("  [%d] CreepJS ID=%s | UA=%s | platform=%s | screen=%sx%s | webgl=%s / %s",
                 i, fp["creepjs_id"], fp["user_agent"], fp["platform"],
                 fp["screen_width"], fp["screen_height"],
                 fp["webgl_vendor"], fp["webgl_renderer"])

    creepjs_ids = [fp["creepjs_id"] for fp in fingerprints]
    assert len(set(creepjs_ids)) == N_CONTEXTS, (
        f"Expected all {N_CONTEXTS} CreepJS fingerprint IDs to be unique, got: {creepjs_ids}"
    )

    log.info("PASS: all CreepJS fingerprint IDs are unique")


def test_contexts_are_isolated(browser):
    """localStorage and cookies must not bleed between contexts."""
    log.info("=== test_contexts_are_isolated: creating 2 contexts ===")
    ctx1 = NewContext(browser)
    ctx2 = NewContext(browser)

    page1 = ctx1.new_page()
    page2 = ctx2.new_page()

    page1.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded")
    page2.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded")

    log.info("Writing localStorage key in context 1...")
    page1.evaluate("localStorage.setItem('camoufox_test', 'secret')")
    value_in_ctx2 = page2.evaluate("localStorage.getItem('camoufox_test')")
    log.info("localStorage 'camoufox_test' in context 2: %s", value_in_ctx2)
    assert value_in_ctx2 is None, (
        f"localStorage leaked from context 1 to context 2: got '{value_in_ctx2}'"
    )
    log.info("PASS: localStorage is isolated")

    log.info("Setting cookie in context 1...")
    ctx1.add_cookies([{
        "name": "camoufox_cookie",
        "value": "ctx1_value",
        "domain": "abrahamjuliot.github.io",
        "path": "/",
    }])
    cookies_in_ctx2 = ctx2.cookies("https://abrahamjuliot.github.io/creepjs/")
    cookie_names = [c["name"] for c in cookies_in_ctx2]
    log.info("Cookies visible in context 2: %s", cookie_names)
    assert "camoufox_cookie" not in cookie_names, (
        f"Cookie leaked from context 1 to context 2: {cookies_in_ctx2}"
    )
    log.info("PASS: cookies are isolated")

    ctx1.close()
    ctx2.close()
    log.info("=== test_contexts_are_isolated complete ===")
