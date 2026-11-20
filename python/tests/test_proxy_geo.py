"""NewContext places a context behind a proxy where the proxy exits.

Two defects left a context with the host's WebRTC IP and timezone while its
traffic went through the proxy:

- The lookup built its own proxy URL with urlparse, which reads a scheme-less
  server such as "1.2.3.4:8080" (a form Playwright accepts) as scheme "1.2.3.4"
  and drops the host.
- A failed lookup was swallowed, and the context launched without the values.

And the lookup moved only the clock: the locale and geolocation stayed the
launch identity's, so a page saw the exit's timezone next to another country's
language and position.

The lookup itself is camoucore's proxy_exit_geo, tested there; these cover
what camoufox hands it and what it does with the answer.
"""

import asyncio
from unittest import mock
from urllib.parse import unquote, urlsplit

import pytest

from camoucore import ip

from camoufox import async_api, sync_api
from camoufox.exceptions import InvalidIP


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


EXIT = {
    "status": "success",
    "query": "203.0.113.7",
    "timezone": "Europe/Paris",
    "countryCode": "FR",
    "lat": 48.8566,
    "lon": 2.3522,
}


def _sync_browser():
    browser = mock.MagicMock()
    browser.version = "152.0.4"
    return browser


def _async_browser():
    context = mock.MagicMock()
    context.add_init_script = mock.AsyncMock()
    browser = mock.MagicMock()
    browser.version = "152.0.4"
    browser.new_context = mock.AsyncMock(return_value=context)
    return browser


def _new_context(api, proxy, **kwargs):
    if api == "sync":
        browser = _sync_browser()
        sync_api.NewContext(browser, os="linux", proxy=proxy, **kwargs)
        return browser.new_context.call_args.kwargs, browser.new_context.return_value
    browser = _async_browser()
    asyncio.run(async_api.AsyncNewContext(browser, os="linux", proxy=proxy, **kwargs))
    return browser.new_context.call_args.kwargs, browser.new_context.return_value


@pytest.mark.parametrize("api", ["sync", "async"])
@pytest.mark.parametrize(
    "server, expected",
    [
        ("1.2.3.4:8080", "http://u:p@1.2.3.4:8080"),
        ("proxy.example.com:8080", "http://u:p@proxy.example.com:8080"),
        ("http://proxy.example.com:8080", "http://u:p@proxy.example.com:8080"),
        ("socks5://proxy.example.com:1080", "socks5://u:p@proxy.example.com:1080"),
    ],
)
def test_lookup_goes_through_the_proxy_with_its_credentials(api, server, expected):
    with mock.patch.object(ip.requests, "get", return_value=_Response(EXIT)) as get:
        options, context = _new_context(api, {"server": server, "username": "u", "password": "p"})
    assert get.call_args.kwargs["proxies"] == {"http": expected, "https": expected}
    assert options["timezone_id"] == "Europe/Paris"
    assert "203.0.113.7" in context.add_init_script.call_args.args[0]


@pytest.mark.parametrize("api", ["sync", "async"])
def test_credentials_with_url_delimiters_survive_the_proxy_url(api):
    # A raw `#`, `/` or `?` stops the URL parsing, and a raw `%41` would be
    # decoded into a different password (#823).
    username, password = "us@r name", "p#ss/w?rd:%41"
    with mock.patch.object(ip.requests, "get", return_value=_Response(EXIT)) as get:
        _new_context(api, {"server": "proxy.example.com:8080", "username": username, "password": password})
    url = urlsplit(get.call_args.kwargs["proxies"]["https"])
    assert (url.hostname, url.port) == ("proxy.example.com", 8080)
    assert (unquote(url.username), unquote(url.password)) == (username, password)


@pytest.mark.parametrize("api", ["sync", "async"])
@pytest.mark.parametrize(
    "failure",
    [
        ip.requests.ConnectionError("proxy refused"),
        _Response({"status": "fail", "message": "private range"}),
    ],
)
def test_a_failed_lookup_raises_instead_of_launching_without_the_values(api, failure):
    get = mock.Mock(side_effect=failure) if isinstance(failure, Exception) else mock.Mock(return_value=failure)
    with mock.patch.object(ip.requests, "get", get), pytest.raises(InvalidIP, match="webrtc_ip"):
        _new_context(api, {"server": "1.2.3.4:8080"})


@pytest.mark.parametrize("api", ["sync", "async"])
def test_the_locale_and_position_move_with_the_clock(api):
    with mock.patch.object(ip.requests, "get", return_value=_Response(EXIT)):
        options, _ = _new_context(api, {"server": "1.2.3.4:8080"})
    assert options["timezone_id"] == "Europe/Paris"
    assert options["locale"].endswith("-FR")
    assert options["geolocation"] == {"latitude": 48.8566, "longitude": 2.3522}
    assert options["permissions"] == ["geolocation"]


@pytest.mark.parametrize("api", ["sync", "async"])
def test_values_the_caller_gave_are_kept(api):
    position = {"latitude": 51.5072, "longitude": -0.1276}
    with mock.patch.object(ip.requests, "get", return_value=_Response(EXIT)):
        options, context = _new_context(
            api, {"server": "1.2.3.4:8080"}, locale="en-GB", geolocation=position
        )
    assert (options["locale"], options["geolocation"]) == ("en-GB", position)
    assert options["timezone_id"] == "Europe/Paris"
    assert "203.0.113.7" in context.add_init_script.call_args.args[0]


@pytest.mark.parametrize("api", ["sync", "async"])
def test_no_lookup_when_every_value_is_given(api):
    with mock.patch.object(ip.requests, "get") as get:
        _new_context(
            api,
            {"server": "1.2.3.4:8080"},
            webrtc_ip="198.51.100.1",
            timezone_id="UTC",
            locale="en-US",
            geolocation={"latitude": 40.7128, "longitude": -74.006},
        )
    get.assert_not_called()
