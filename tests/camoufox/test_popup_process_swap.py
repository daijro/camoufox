# Popup process-swap zombie-target guard.
#
# When a popup created via window.open() navigates cross-origin, Firefox may
# fire TabOpen a second time for the same browsing context, constructing a
# second PageTarget for the same browserId. Without the guard, the old target
# is silently replaced in the registry and never disposed, leaving an
# orphaned session on the client: every evaluate against it hangs with
# 'juggler: timeout waiting for Runtime.evaluate', and Playwright reports the
# page as closed even though the tab is alive.
#
# These tests assert no duplicate targets appear for the same browsing context
# after cross-origin popup navigation.

from playwright.async_api import Browser, Page


async def test_popup_cross_origin_keeps_one_target_per_browsing_context(
    browser: Browser,
) -> None:
    context = await browser.new_context()
    opener = await context.new_page()
    await opener.goto("data:text/html,<button onclick=\"window.open('about:blank','p')\">o</button>")
    async with opener.expect_page() as popup_info:
        await opener.click("button")
    popup = await popup_info.value
    await popup.goto("data:text/html,<h1 id=x>cross-origin</h1>")
    await popup.wait_for_selector("#x")
    # Give the registry a beat to process any late TabOpen.
    await opener.wait_for_timeout(200)

    pages = context.pages
    assert len(pages) == 2, f"expected 2 pages, got {len(pages)}: {[p.url for p in pages]}"

    await context.close()


async def test_zombie_target_disposed_on_re_registration(browser: Browser) -> None:
    context = await browser.new_context()
    opener = await context.new_page()
    await opener.goto("data:text/html,<button onclick=\"window.open('about:blank','p')\">o</button>")
    async with opener.expect_page() as popup_info:
        await opener.click("button")
    popup = await popup_info.value

    # Navigate cross-origin to trigger any re-registration path.
    await popup.goto("data:text/html,<h1 id=y>second origin</h1>")
    await popup.wait_for_selector("#y")
    await opener.wait_for_timeout(200)

    pages: list[Page] = context.pages
    urls = [p.url for p in pages]
    assert len(urls) == len(set(urls)), f"duplicate targets registered: {urls}"
    assert any("second origin" in u for u in urls)

    await context.close()
