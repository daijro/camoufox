# Camoufox-specific: page.route() must not change what a request looks like on the wire.
#
# Enabling request interception used to alter every request the page made, which let anti-bot
# services tell an intercepted page apart from a normal one (daijro/camoufox#428, #271):
#
#   - Playwright pairs every setRequestInterception() with setCacheDisabled(true), and the load
#     flags behind that made necko attach "Pragma: no-cache" / "Cache-Control: no-cache", which
#     Firefox otherwise only sends for a forced reload.
#   - Resuming an intercepted request rebuilds the channel, and the header copy that follows
#     leaves "connection" and "cookie" appended after the sec-fetch-* headers instead of in
#     front of them.
#
# These tests compare a routed page against an unrouted one rather than hardcoding a header
# layout, so they keep working as the underlying Firefox changes.

from typing import Dict, List, Tuple

from playwright.async_api import BrowserContext, Page, Route
from tests.server import Server, TestServerRequest


async def _request_headers(context: BrowserContext, server: Server, intercept: bool) -> List[Tuple[str, str]]:
    """Load a page and return the document request's headers, in the order they arrived."""
    seen: List[Tuple[str, str]] = []

    def _handler(request: TestServerRequest) -> None:
        # getAllRawHeaders() yields bytes, in the order the headers arrived.
        for name, values in request.requestHeaders.getAllRawHeaders():
            for value in values:
                seen.append((name.decode().lower(), value.decode()))
        request.setHeader("content-type", "text/html")
        request.write(b"<html><body>hi</body></html>")
        request.finish()

    server.set_route("/fingerprint.html", _handler)

    page = await context.new_page()
    if intercept:
        await page.route("**/*", lambda route: route.continue_())
    await page.goto(server.PREFIX + "/fingerprint.html")
    await page.close()
    return seen


async def test_page_route_should_not_change_request_headers(context: BrowserContext, server: Server) -> None:
    await context.add_cookies([{"name": "sid", "value": "x", "url": server.PREFIX}])

    without_route = await _request_headers(context, server, intercept=False)
    with_route = await _request_headers(context, server, intercept=True)

    assert with_route == without_route


async def test_page_route_should_not_change_request_headers_with_extra_http_headers(
    context: BrowserContext, server: Server
) -> None:
    # The extra headers are added at http-on-modify-request, which is after the cookie header,
    # so they have to be accounted for when putting the cookie header back.
    await context.add_cookies([{"name": "sid", "value": "x", "url": server.PREFIX}])
    await context.set_extra_http_headers({"x-custom-hdr": "v1"})

    without_route = await _request_headers(context, server, intercept=False)
    with_route = await _request_headers(context, server, intercept=True)

    assert with_route == without_route


async def test_page_route_should_not_advertise_a_disabled_cache(context: BrowserContext, server: Server) -> None:
    headers: Dict[str, str] = dict(await _request_headers(context, server, intercept=True))

    # Firefox sends these on a forced reload. A routed page is not a forced reload.
    assert "pragma" not in headers
    assert headers.get("cache-control") != "no-cache"


async def test_page_route_should_not_reorder_connection_and_cookie(context: BrowserContext, server: Server) -> None:
    await context.add_cookies([{"name": "sid", "value": "x", "url": server.PREFIX}])

    names = [name for name, _ in await _request_headers(context, server, intercept=True)]

    # Both are added before necko appends the sec-fetch-* headers.
    assert names.index("connection") < names.index("sec-fetch-mode")
    assert names.index("cookie") < names.index("sec-fetch-mode")
