# Camoufox-specific: a response body must be readable when its encoding header says "identity".
#
# Juggler decodes a stored body by running each listed encoding through a stream converter.
# "identity" means no encoding, and Firefox skips it when it applies content conversions, so
# no converter is registered for it and response.text() failed with NS_ERROR_FAILURE while the
# page itself rendered (daijro/camoufox#867). microsoft/playwright fixed its Juggler and added a
# test in 1.63 (#42501, #42537); playwright-python, whose suite runs here, has no such test.

import pytest

from playwright.async_api import Page
from tests.server import Server, TestServerRequest


@pytest.mark.parametrize("encoding", ["identity", "Identity", "x-identity", "identity, identity"])
async def test_response_text_with_identity_content_encoding(page: Page, server: Server, encoding: str) -> None:
    def handler(request: TestServerRequest) -> None:
        request.setHeader("content-type", "text/plain; charset=utf-8")
        request.setHeader("content-encoding", encoding)
        request.write(b"hello")
        request.finish()

    server.set_route("/identity", handler)

    response = await page.goto(server.PREFIX + "/identity")
    assert response
    assert await response.text() == "hello"
