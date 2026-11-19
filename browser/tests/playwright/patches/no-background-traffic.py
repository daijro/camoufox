"""
An idle browser sends nothing, and Push connects only when a page subscribes.

Firefox's background services (Remote Settings, Push, connectivity and captive
portal probes, Safe Browsing, region lookup, new tab feeds) make requests no
page asked for, seen by whoever runs the proxy. A page cannot see them, so
Camoufox makes none. Every connection goes through a logging proxy here, set by
prefs so that services outside a browser context take it too.

The media plugin downloads stay on, and the idle check turns them off to see
everything else: a page can see OpenH264 and Widevine, so they are not background
in that sense (rule no-background-traffic).

What PASS means:
    * the proxy works: a navigation reaches it, so silence means something;
    * a fresh profile left idle, with plugin updates off, sends nothing else;
    * pushManager.subscribe() still opens a connection to the push server, so
      Push is on demand rather than off.

    python browser/tests/playwright/patches/no-background-traffic.py
"""

import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# A build without the fix shows every background service named above within this
# long on a fresh profile.
IDLE_SECONDS = 60
CONTROL_HOST = "control.camoufox.test"
PUSH_HOST = "push.camoufox.test"
SUBSCRIBE_SECONDS = 20


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


def launch(proxy: LoggingProxy, **prefs):
    from camoufox.sync_api import Camoufox

    port = proxy.server_address[1]
    return Camoufox(
        headless=True,
        os="linux",
        executable_path=str(resolve_binary()),
        i_know_what_im_doing=True,
        firefox_user_prefs={
            "network.proxy.type": 1,
            "network.proxy.http": "127.0.0.1",
            "network.proxy.http_port": port,
            "network.proxy.ssl": "127.0.0.1",
            "network.proxy.ssl_port": port,
            **prefs,
        },
    )


def main() -> int:
    proxy = LoggingProxy()
    with launch(proxy, **{"media.gmp-manager.updateEnabled": False}) as browser:
        page = browser.new_page()
        time.sleep(IDLE_SECONDS)
        idle = list(proxy.seen)
        try:
            page.goto(f"http://{CONTROL_HOST}/", timeout=10_000)
        except Exception:
            pass
    control = [seen for seen in proxy.seen if CONTROL_HOST in seen]

    site = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Site)
    site.daemon_threads = True
    threading.Thread(target=site.serve_forever, daemon=True).start()
    proxy.seen.clear()
    with launch(proxy, **{"dom.push.serverURL": f"wss://{PUSH_HOST}/"}) as browser:
        context = browser.new_context()
        context.grant_permissions(["notifications"])
        page = context.new_page()
        page.goto(f"http://localhost:{site.server_address[1]}/")
        time.sleep(2)
        before_subscribe = [seen for seen in proxy.seen if PUSH_HOST in seen]
        page.evaluate(
            "void navigator.serviceWorker.register('/sw.js')"
            ".then(() => navigator.serviceWorker.ready)"
            ".then(r => r.pushManager.subscribe({ userVisibleOnly: true }))"
        )
        deadline = time.monotonic() + SUBSCRIBE_SECONDS
        while time.monotonic() < deadline and not any(PUSH_HOST in seen for seen in proxy.seen):
            time.sleep(0.2)
        after_subscribe = [seen for seen in proxy.seen if PUSH_HOST in seen]

    checks = [
        ("the proxy sees a navigation", bool(control), control),
        (f"idle for {IDLE_SECONDS} s: no request", not idle, idle),
        ("no push connection before a page subscribes", not before_subscribe, before_subscribe),
        ("a subscription connects to the push server", bool(after_subscribe), after_subscribe),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
