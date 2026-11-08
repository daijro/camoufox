r"""
A NewContext() identity's requests all carry its own User-Agent header.

Juggler gives a context's documents their user agent through the browsing
context (customUserAgent), so a request with no browsing context of its own
sent the launch's instead: a shared worker's script and its fetches, a CSP
violation report, a keepalive fetch. A server reads that in its access log.
HttpBaseChannel::SetDocshellUserAgentOverride now falls back to the context's
own user agent (NavigatorManager, by userContextId).

The launch and context use different user agents the way NewContext() supplies
them (Playwright's user_agent for Juggler's documents, the
setNavigatorUserAgent setter for everything else), so the launch's user agent
can never pass for the context's.

    python browser/tests/playwright/patches/context-http-user-agent.py
"""

import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

PAGE = b"""<!doctype html><body><p>x</p><script>
(async () => {
  const sw = new SharedWorker('/shared.js');
  await new Promise(r => { sw.port.onmessage = r; });
  const w = new Worker('/dedicated.js');
  await new Promise(r => { w.onmessage = r; });
  await fetch('/keepalive', {method: 'POST', body: 'x', keepalive: true});
  const img = document.createElement('img');
  img.src = '/blocked.png';  // img-src 'none': a CSP violation report
  document.body.appendChild(img);
})();
</script></body>"""
WORKER = {
    "/shared.js": b"onconnect = e => { fetch('/from-shared').then(() => e.ports[0].postMessage(1)); };",
    "/dedicated.js": b"fetch('/from-dedicated').then(() => postMessage(1));",
}
CSP = "img-src 'none'; report-uri /csp-report"
CONTEXT_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0"


class _Server(http.server.BaseHTTPRequestHandler):
    seen: dict = {}

    def log_message(self, *args):
        pass

    def _note(self):
        _Server.seen.setdefault(self.path.split("?")[0], self.headers.get("User-Agent"))

    def do_GET(self):
        self._note()
        if self.path.startswith("/page"):
            body, ctype = PAGE, "text/html"
        elif self.path in WORKER:
            body, ctype = WORKER[self.path], "text/javascript"
        else:
            body, ctype = b"ok", "text/plain"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if self.path.startswith("/page"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._note()
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(204)
        self.end_headers()


def main() -> int:
    import json

    from camoufox.sync_api import Camoufox

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/page"

    failures = []
    with Camoufox(**launch_kwargs(os="windows", canvas_noise=True, i_know_what_im_doing=True)) as browser:
        context = browser.new_context(user_agent=CONTEXT_UA)
        context.add_init_script(
            f'if (typeof window.setNavigatorUserAgent === "function") window.setNavigatorUserAgent({json.dumps(CONTEXT_UA)});')
        page = context.new_page()
        page.goto(url)
        # Camoufox evaluates in an isolated world, which does not see the page's
        # globals; the page's own requests are what the server waits for.
        ua = page.evaluate("navigator.userAgent")
        deadline = time.time() + 10
        want = ("/page", "/shared.js", "/from-shared", "/dedicated.js", "/from-dedicated", "/keepalive", "/csp-report")
        while time.time() < deadline and not all(p in _Server.seen for p in want):
            time.sleep(0.2)
        context.close()
    server.shutdown()

    print(f"  context navigator.userAgent: {ua}")
    for path in want:
        got = _Server.seen.get(path)
        print(f"  {path:16s} {got}")
        if got is None:
            failures.append(f"{path}: never requested")
        elif got != ua:
            failures.append(f"{path}: User-Agent {got!r}, the context's is {ua!r}")
    if "Linux" not in ua or "Windows" in ua:
        failures.append(f"the context did not claim Linux: {ua!r}")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: every request of a context carries the context's own User-Agent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
