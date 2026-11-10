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

import pytest

from playwright.async_api import BrowserContext, Route
from tests.server import Server, TestServerRequest


async def _continue_route(route: Route, forward_headers: bool) -> None:
    if forward_headers:
        await route.continue_(headers=await route.request.all_headers())
    else:
        await route.continue_()


async def _request_headers(
    context: BrowserContext, server: Server, intercept: bool, forward_headers: bool = False
) -> List[Tuple[str, str]]:
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
        await page.route("**/*", lambda route: _continue_route(route, forward_headers))
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


async def _subresource_headers(context: BrowserContext, server: Server, intercept: bool, tag: str) -> List[str]:
    """Load a page that requests a subresource and return that request's header names, in order."""
    seen: List[str] = []

    def _document(request: TestServerRequest) -> None:
        request.setHeader("content-type", "text/html")
        if tag == "img":
            request.write(b'<html><body><img src="/sub.png"></body></html>')
        else:
            request.write(b"<html><body><script>fetch('/sub.png')</script></body></html>")
        request.finish()

    def _subresource(request: TestServerRequest) -> None:
        for name, values in request.requestHeaders.getAllRawHeaders():
            seen.extend(name.decode().lower() for _ in values)
        request.setHeader("content-type", "image/png")
        request.finish()

    server.set_route("/sub-document.html", _document)
    server.set_route("/sub.png", _subresource)

    page = await context.new_page()
    if intercept:
        await page.route("**/*", lambda route: route.continue_())
    async with page.expect_request_finished(lambda r: r.url.endswith("/sub.png")):
        await page.goto(server.PREFIX + "/sub-document.html")
    await page.close()
    return seen


async def test_page_route_should_not_reorder_subresource_headers(context: BrowserContext, server: Server) -> None:
    # A subresource carries a referer. Stock sends it after "connection" for an <img> (necko sets a
    # default-policy referer again after adding "connection") and before it for fetch().
    for tag in ("img", "fetch"):
        without_route = await _subresource_headers(context, server, intercept=False, tag=tag)
        with_route = await _subresource_headers(context, server, intercept=True, tag=tag)
        assert with_route == without_route, tag


async def test_page_route_should_preserve_order_when_continuing_with_headers(
    context: BrowserContext, server: Server
) -> None:
    await context.add_cookies([{"name": "sid", "value": "x", "url": server.PREFIX}])

    without_route = await _request_headers(context, server, intercept=False)
    with_route = await _request_headers(
        context, server, intercept=True, forward_headers=True
    )

    assert with_route == without_route


@pytest.mark.parametrize("forward_headers", [False, True])
async def test_page_route_should_preserve_fetch_header_order(
    context: BrowserContext, server: Server, forward_headers: bool
) -> None:
    # A fetch() with a header of its own: a resumed one sent "connection" ahead of its referer and
    # that header, where the same fetch unrouted sends it after them.
    async def _fetch_headers(intercept: bool) -> List[Tuple[str, str]]:
        seen: List[Tuple[str, str]] = []

        def _page(request: TestServerRequest) -> None:
            request.setHeader("content-type", "text/html")
            request.write(
                b"<script>fetch('/fingerprint-fetch', {headers: {'X-A': '1'}}).then(() => "
                b"document.documentElement.dataset.fetched = 'true')</script>"
            )
            request.finish()

        def _fetch(request: TestServerRequest) -> None:
            for name, values in request.requestHeaders.getAllRawHeaders():
                for value in values:
                    seen.append((name.decode().lower(), value.decode()))
            request.write(b"ok")
            request.finish()

        server.set_route("/fingerprint-fetch.html", _page)
        server.set_route("/fingerprint-fetch", _fetch)
        page = await context.new_page()
        if intercept:
            await page.route(
                "**/*", lambda route: _continue_route(route, forward_headers)
            )
        await page.goto(server.PREFIX + "/fingerprint-fetch.html")
        await page.wait_for_function(
            "document.documentElement.dataset.fetched === 'true'"
        )
        await page.close()
        return seen

    await context.add_cookies([{"name": "sid", "value": "x", "url": server.PREFIX}])
    without_route = await _fetch_headers(intercept=False)
    with_route = await _fetch_headers(intercept=True)

    assert with_route == without_route


async def test_page_route_installs_and_fulfils(context: BrowserContext, server: Server) -> None:
    # Playwright >= 1.64 passes bypassServiceWorker with Network.setRequestInterception. A browser
    # that rejects the parameter fails every page.route() call outright (daijro/camoufox#873).
    server.set_route("/probe.html", lambda request: (
        request.setHeader("content-type", "text/html"),
        request.write(b"<html><body>probe</body></html>"),
        request.finish(),
    ))
    hits: List[str] = []

    async def _handler(route) -> None:
        hits.append(route.request.url)
        await route.fulfill(body="intercepted")

    page = await context.new_page()
    await page.route("**/probe.txt", _handler)
    await page.goto(server.PREFIX + "/probe.html")

    assert await page.evaluate("fetch('/probe.txt').then(r => r.text())") == "intercepted"
    assert hits == [server.PREFIX + "/probe.txt"]


async def test_storage_state_capture_installs_interception(context: BrowserContext) -> None:
    # Storage-state capture drives the internal page that passes bypassServiceWorker: true, so the
    # flag's path is exercised here even though Playwright exposes no way to observe its effect.
    page = await context.new_page()
    await page.set_content("<html><body>probe</body></html>")

    state = await context.storage_state()

    assert "cookies" in state
