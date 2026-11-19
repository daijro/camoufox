# A response body must be readable after the connection drops mid-stream.
#
# When a response ends with an error (Firefox: NS_ERROR_NET_PARTIAL_TRANSFER from
# a connection closed before the terminating chunk), the page has still read
# every byte delivered. Juggler's NetworkObserver buffers those bytes in
# _responseBodyChunks, but only offered them to Network.getResponseBody when the
# request succeeded; on aStatusCode != 0 it deleted the chunks, so
# response.body() threw "Request ... is not found" and lost the data
# (daijro/camoufox#999). The bytes delivered before the failure are now stored,
# while requestfailed and request.failure() still report the error.

import asyncio
from typing import Optional

from playwright.async_api import Page, Request, Response
from twisted.internet import reactor

from tests.server import Server, TestServerRequest


async def test_response_body_after_partial_transfer(
    page: Page, server: Server
) -> None:
    lines = [f'{{"line": {i}}}\n' for i in range(20)]
    expected = "".join(lines)

    def handler(request: TestServerRequest) -> None:
        # Write the full body without a terminating zero-length chunk, then drop
        # the connection, so the client sees a truncated response.
        request.setHeader("content-type", "application/x-ndjson")
        request.write(expected.encode())
        # Drop the TCP connection from the server side after the bytes are out.
        reactor.callLater(0.05, request.channel.transport.loseConnection)  # type: ignore[attr-defined]

    server.set_route("/stream", handler)

    # The fetch below must be same-origin: a page on about:blank fetching
    # server.PREFIX is cross-origin, and without CORS headers that fails with a
    # NetworkError before any byte arrives (the issue's repro navigates first).
    await page.goto(server.EMPTY_PAGE)

    loop = asyncio.get_running_loop()
    failed_promise: "asyncio.Future[Request]" = loop.create_future()

    def on_failed(request: Request) -> None:
        if request.url.endswith("/stream") and not failed_promise.done():
            failed_promise.set_result(request)

    # Register before the fetch: the events fire while the page reads the stream.
    page.on("requestfailed", on_failed)
    try:
        async with page.expect_response(lambda r: r.url.endswith("/stream")) as resp_info:
            page_text = await page.evaluate(
                """async (url) => {
                    const reader = (await fetch(url)).body.getReader();
                    const decoder = new TextDecoder();
                    let text = "";
                    try {
                        for (;;) {
                            const { done, value } = await reader.read();
                            if (done) break;
                            text += decoder.decode(value, { stream: true });
                        }
                    } catch {
                        // connection dropped after the last line
                    }
                    return text;
                }""",
                server.PREFIX + "/stream",
            )
        failed: Optional[Request] = await asyncio.wait_for(failed_promise, timeout=10)
    finally:
        page.remove_listener("requestfailed", on_failed)

    assert page_text == expected, "the page received every line"
    assert failed is not None and failed.failure is not None
    assert "NS_ERROR_NET_PARTIAL_TRANSFER" in (failed.failure or ""), failed.failure

    response: Optional[Response] = await resp_info.value
    assert response is not None
    assert (await response.body()).decode() == expected
