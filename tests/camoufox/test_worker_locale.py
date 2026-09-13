# A worker must agree with its page about the locale.
#
# Upstream's tests/async/test_worker.py asserts the opposite for Firefox, with a
# link to microsoft/playwright#38919:
#
#     expected = "10,000.2" if browser_name == "firefox" else "10 000,2"
#
# That is stock Firefox leaking en-US into a worker created from a ru-RU
# context, because Playwright's locale override is applied to the page and not
# below it. Camoufox sets the locale underneath that layer, so the worker sees
# the same locale the main thread does and prints what a genuinely ru-RU Firefox
# prints.
#
# The disagreement upstream encodes is a free fingerprinting signal: read
# Intl.DateTimeFormat().resolvedOptions() on the main thread, read it again in a
# worker, compare. Matching upstream would mean reintroducing it, so the
# upstream test is skiplisted (ci/skiplist.yml) and this one guards the
# behaviour instead.

from playwright.async_api import Browser

from tests.server import Server

# Russian groups with a narrow no-break space and uses a comma for the decimal
# separator; en-US does the reverse. The two are unambiguous.
RU_RU = "10 000,2"


async def test_worker_should_inherit_the_context_locale(browser: Browser, server: Server) -> None:
    context = await browser.new_context(locale="ru-RU")
    page = await context.new_page()
    await page.goto(server.EMPTY_PAGE)

    async with page.expect_worker() as worker_info:
        await page.evaluate(
            "() => new Worker(URL.createObjectURL(new Blob(['console.log(1)'],"
            " {type: 'application/javascript'})))"
        )
    worker = await worker_info.value

    assert await worker.evaluate("() => (10000.20).toLocaleString()") == RU_RU
    await context.close()


async def test_worker_and_page_agree_on_the_locale(browser: Browser, server: Server) -> None:
    # The tell is the disagreement, not either value on its own, so compare the
    # two directly rather than trusting one hardcoded string to catch it.
    context = await browser.new_context(locale="ru-RU")
    page = await context.new_page()
    await page.goto(server.EMPTY_PAGE)

    async with page.expect_worker() as worker_info:
        await page.evaluate(
            "() => new Worker(URL.createObjectURL(new Blob(['console.log(1)'],"
            " {type: 'application/javascript'})))"
        )
    worker = await worker_info.value

    probe = "() => Intl.NumberFormat().resolvedOptions().locale"
    assert await worker.evaluate(probe) == await page.evaluate(probe)
    await context.close()
