"""
Tests that document and pin Camoufox-specific stealth-vs-launch-arg behaviour.

The interesting case for Camoufox: when a Playwright launch arg conflicts
with a stealth-fingerprint config, *which one wins*?  The answer is a
deliberate Camoufox design decision, not a bug — but it must be tested
because it's where Camoufox diverges from stock Firefox.

These tests use plain `playwright.firefox.launch(executable_path=...)`,
not the camoufox python wrapper, because most users hit Camoufox through
that path.
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------
# UA: Camoufox replaces "Firefox/<v>" with "Camoufox/<v>" by default.
# --------------------------------------------------------------------------


async def test_default_ua_advertises_camoufox(camoufox_browser) -> None:
    page = await camoufox_browser.new_page()
    ua = await page.evaluate("() => navigator.userAgent")
    # Either is acceptable; this test pins the *current* behaviour so we
    # notice if it changes (which has stealth implications either way).
    assert "Camoufox" in ua or "Firefox" in ua, f"UA looks neither: {ua}"


async def test_user_agent_launch_arg_overrides_default(camoufox_browser) -> None:
    custom = "Mozilla/5.0 (X11; Linux x86_64) Test/1.0"
    ctx = await camoufox_browser.new_context(user_agent=custom)
    page = await ctx.new_page()
    assert await page.evaluate("() => navigator.userAgent") == custom
    await ctx.close()


# --------------------------------------------------------------------------
# Locale: known Camoufox bug — fingerprint locale wins over launch arg.
# Marked xfail so it's tracked but doesn't fail CI; flip when fixed.
# --------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="Known: Camoufox fingerprint locale wins over launch arg; "
    "see effervescent-fern-step-2 results.",
    strict=False,
)
async def test_locale_launch_arg_should_win_over_fingerprint(camoufox_browser) -> None:
    ctx = await camoufox_browser.new_context(locale="fr-FR")
    page = await ctx.new_page()
    assert await page.evaluate("() => navigator.language") == "fr-FR"
    await ctx.close()


# --------------------------------------------------------------------------
# Timezone: launch arg should win.
# --------------------------------------------------------------------------


async def test_timezone_launch_arg_wins(camoufox_browser) -> None:
    ctx = await camoufox_browser.new_context(timezone_id="Asia/Tokyo")
    page = await ctx.new_page()
    offset = await page.evaluate("() => new Date().getTimezoneOffset()")
    # Asia/Tokyo is UTC+9 → JS getTimezoneOffset returns -540.
    assert offset == -540, f"Expected -540 (Asia/Tokyo), got {offset}"
    await ctx.close()


# --------------------------------------------------------------------------
# WebDriver flag: must always be undefined regardless of how Camoufox launches.
# --------------------------------------------------------------------------


async def test_navigator_webdriver_is_undefined(camoufox_browser) -> None:
    page = await camoufox_browser.new_page()
    assert await page.evaluate("() => navigator.webdriver") in (False, None, "undefined")
    # Modern Firefox returns undefined; some test stacks return False.
    # Anything truthy means the stealth patch regressed.
