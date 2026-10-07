# What the bare binary advertises as its User-Agent.
#
# Upstream's tests/async/test_network.py::test_request_headers_should_work
# asserts `"Firefox" in user-agent`. That holds for how Camoufox is actually
# used -- the Python package replaces the token with "Firefox/<version>" on the
# wire and in navigator.userAgent as part of injecting a fingerprint -- but this
# suite drives the bare binary through plain Playwright, with no package and no
# fingerprint, and the bare binary advertises its own build token:
#
#     Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Camoufox/152.0
#
# So the upstream test is skiplisted (ci/skiplist.yml) and this one takes over,
# asserting what this layer can actually promise: a well-formed Gecko UA
# carrying exactly one of the two tokens, matching between the wire and the DOM.
#
# The last assertion is the one that matters for the fork. A UA that differs
# between the request header and navigator.userAgent is a one-line detection,
# and it is the failure this file exists to catch.

import re

from playwright.async_api import Page

from tests.server import Server

# "Camoufox/152.0" or "Firefox/152.0" -- either is a coherent answer, one of
# them is required, and the version has to look like a version.
UA_TOKEN = re.compile(r"\b(Camoufox|Firefox)/(\d+(?:\.\d+)*)\b")


async def test_user_agent_carries_a_gecko_build_token(page: Page, server: Server) -> None:
    response = await page.goto(server.EMPTY_PAGE)
    assert response

    user_agent = response.request.headers["user-agent"]
    assert "Gecko/20100101" in user_agent, user_agent

    token = UA_TOKEN.search(user_agent)
    assert token, f"no Camoufox/ or Firefox/ token in {user_agent!r}"


async def test_user_agent_matches_between_the_wire_and_the_dom(page: Page, server: Server) -> None:
    response = await page.goto(server.EMPTY_PAGE)
    assert response

    assert response.request.headers["user-agent"] == await page.evaluate(
        "() => navigator.userAgent"
    )
