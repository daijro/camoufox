"""
With proxies on contexts only, the browser's own traffic goes through one too.

A launch can leave the browser without a proxy and give each context its own
(new_context(proxy=...)), one identity per context. The browser's own
connections belong to no context: the push websocket every context shares,
media plugin update checks. Juggler gave them no proxy, so they went out
direct from this machine's address (5 direct connections in 120 s, measured
2026-11-09), while every page went through its proxy. They now take the newest
proxied context's proxy (TargetRegistry.getProxyInfo).

The push server is pointed at a host only a proxy can see, so the check needs
no network: a page in the proxied context subscribes, and the push connection
must reach the logging proxy.

What PASS means:
    * the proxy works: the proxied context's navigation reaches it;
    * the subscription's push connection, which no page owns, reaches it too.

    python browser/tests/playwright/patches/context-proxy-browser-traffic.py
"""

import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

CONTROL_HOST = "control.camoufox.test"
PUSH_HOST = "push.camoufox.test"
SUBSCRIBE_SECONDS = 30


class Logging(http.server.BaseHTTPRequestHandler):
    def _refuse(self) -> None:
        self.server.seen.append(self.path)
        self.send_error(502)

    do_CONNECT = do_GET = do_POST = _refuse

    def log_message(self, *args) -> None:
        pass


class LoggingProxy(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Logging)
        self.seen = []
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        worker = self.path == "/sw.js"
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript" if worker else "text/html")
        self.end_headers()
        self.wfile.write(b"" if worker else b"<!doctype html>")

    def log_message(self, *args) -> None:
        pass


def main() -> int:
    from camoufox.sync_api import Camoufox

    proxy = LoggingProxy()
    site = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Site)
    site.daemon_threads = True
    threading.Thread(target=site.serve_forever, daemon=True).start()

    with Camoufox(
        headless=True,
        os="linux",
        executable_path=str(resolve_binary()),
        i_know_what_im_doing=True,
        firefox_user_prefs={"dom.push.serverURL": f"wss://{PUSH_HOST}/"},
    ) as browser:
        context = browser.new_context(proxy={"server": f"http://127.0.0.1:{proxy.server_address[1]}"})
        context.grant_permissions(["notifications"])
        page = context.new_page()
        try:
            page.goto(f"http://{CONTROL_HOST}/", timeout=10_000)
        except Exception:
            pass
        control = [seen for seen in proxy.seen if CONTROL_HOST in seen]

        # localhost is never proxied, so the page itself loads direct; only
        # the push connection it causes is the browser's own.
        page.goto(f"http://localhost:{site.server_address[1]}/")
        page.evaluate(
            "void navigator.serviceWorker.register('/sw.js')"
            ".then(() => navigator.serviceWorker.ready)"
            ".then(r => r.pushManager.subscribe({ userVisibleOnly: true }))"
        )
        deadline = time.monotonic() + SUBSCRIBE_SECONDS
        while time.monotonic() < deadline and not any(PUSH_HOST in seen for seen in proxy.seen):
            time.sleep(0.2)
        push = [seen for seen in proxy.seen if PUSH_HOST in seen]

    checks = [
        ("the context's navigation reaches its proxy", bool(control), control),
        ("the push connection reaches it too", bool(push), push),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
