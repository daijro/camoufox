# What the bare binary advertises as its User-Agent.
#
# Upstream's tests/async/test_network.py::test_request_headers_should_work only
# asserts `"Firefox" in user-agent`. A UA of "... Firefox/156.0 Camoufox/156.0"
# passes that and still names the browser to every site, so this asserts the
# whole shape stock Firefox sends: the app token is Firefox/<major>.0, matching
# rv:, nothing follows it, and the header agrees with navigator.userAgent.

import re

from playwright.async_api import Page

from tests.server import Server

STOCK_UA = re.compile(r"^Mozilla/5\.0 \([^)]+; rv:(\d+)\.0\) Gecko/20100101 Firefox/\1\.0$")


async def test_user_agent_is_stock_firefox(page: Page, server: Server) -> None:
    response = await page.goto(server.EMPTY_PAGE)
    assert response

    user_agent = response.request.headers["user-agent"]
    assert STOCK_UA.match(user_agent), user_agent


async def test_user_agent_matches_between_the_wire_and_the_dom(page: Page, server: Server) -> None:
    response = await page.goto(server.EMPTY_PAGE)
    assert response

    assert response.request.headers["user-agent"] == await page.evaluate(
        "() => navigator.userAgent"
    )
