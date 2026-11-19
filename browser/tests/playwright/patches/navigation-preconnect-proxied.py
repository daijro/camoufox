"""
A navigation's preconnect and a document's DNS prefetch obey the proxy and routes.

Page.navigate preconnects to the host before the content process asks, as
stock's own loads do. That connection is opened outside the page's load, so it
must take the same path the load does: through a Juggler proxy when the context
has one, and nowhere at all when the caller's route answers the request. A
connection around the proxy shows the exit's server the machine's real address.

The origin listens on this host's own address, which is not loopback (Firefox
never proxies loopback), so a connection reaching it went around the proxy.

What PASS means:
    * direct, the origin is reached: the address works, so silence means something;
    * behind a context proxy and a launch proxy, the proxy serves the page and
      the origin hears nothing;
    * with a route fulfilling the request, the origin hears nothing;
    * a dns-prefetch link in a document that loaded nothing through the proxy
      resolves the name on this machine only when no proxy is in play, which
      the resolver's log shows.

    python browser/tests/playwright/patches/navigation-preconnect-proxied.py
"""

import http.server
import os
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import own_address, resolve_binary  # noqa: E402

PAGE = b"<!doctype html><title>page</title>"
# Long enough for a preconnect behind a finished load to reach the listener.
SETTLE_SECONDS = 1


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args) -> None:
        pass


class Listener(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Serves the page and counts every TCP connection, used or not."""

    daemon_threads = True

    def __init__(self, host: str) -> None:
        super().__init__((host, 0), Page)
        self.connections = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def get_request(self):
        accepted = super().get_request()
        self.connections += 1
        return accepted


def connections_during(listener: Listener, action) -> int:
    before = listener.connections
    action()
    time.sleep(SETTLE_SECONDS)
    return listener.connections - before


def prefetch_from(context, name: str) -> None:
    """Open a route-fulfilled document, so no load shows Firefox the proxy."""
    page = context.new_page()
    body = f'<!doctype html><link rel="dns-prefetch" href="//{name}">'
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=body))
    page.goto("http://document.test/")
    time.sleep(SETTLE_SECONDS)


def main() -> int:
    from camoufox.sync_api import Camoufox

    origin = Listener(own_address())
    proxy = Listener("127.0.0.1")
    url = f"http://{origin.server_address[0]}:{origin.server_address[1]}/"
    server = f"http://127.0.0.1:{proxy.server_address[1]}"
    resolver_log = tempfile.TemporaryDirectory()
    env = {**os.environ, "MOZ_LOG": "append,nsHostResolver:5", "MOZ_LOG_FILE": str(Path(resolver_log.name) / "resolver")}
    launch = dict(headless=True, os="linux", executable_path=str(resolve_binary()), i_know_what_im_doing=True, env=env)

    with Camoufox(**launch) as browser:
        # First: a proxied context turns prefetch off for the whole browser.
        prefetch_from(browser.new_context(), "direct-prefetch.test")
        prefetch_from(browser.new_context(proxy={"server": server}), "context-prefetch.test")
    with Camoufox(**launch, proxy={"server": server}, geoip=False) as browser:
        prefetch_from(browser.new_context(), "launch-prefetch.test")
    resolved = "".join(path.read_text(errors="replace") for path in Path(resolver_log.name).iterdir())
    resolver_log.cleanup()

    with Camoufox(**launch) as browser:
        direct = connections_during(origin, lambda: browser.new_page().goto(url))
        served_before = proxy.connections
        around_context = connections_during(
            origin, lambda: browser.new_context(proxy={"server": server}).new_page().goto(url))
        served_context = proxy.connections - served_before

        routed_page = browser.new_page()
        routed_page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=PAGE))
        around_route = connections_during(origin, lambda: routed_page.goto(url))

    with Camoufox(**launch, proxy={"server": server}, geoip=False) as browser:
        served_before = proxy.connections
        around_launch = connections_during(origin, lambda: browser.new_page().goto(url))
        served_launch = proxy.connections - served_before

    checks = [
        ("direct: the origin is reached", direct >= 1, direct),
        ("context proxy: the proxy serves the page", served_context >= 1, served_context),
        ("context proxy: nothing went around it", around_context == 0, around_context),
        ("launch proxy: the proxy serves the page", served_launch >= 1, served_launch),
        ("launch proxy: nothing went around it", around_launch == 0, around_launch),
        ("a route answers the request: the origin hears nothing", around_route == 0, around_route),
        ("direct: a dns-prefetch link is resolved", "direct-prefetch.test" in resolved, len(resolved)),
        ("context proxy: a dns-prefetch link is not resolved here", "context-prefetch.test" not in resolved, ""),
        ("launch proxy: a dns-prefetch link is not resolved here", "launch-prefetch.test" not in resolved, ""),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
