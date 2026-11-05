"""
A driver's click on a point an open chrome popup covers goes to the popup at once, as an OS click does.

The parent hands a mouse event inside a visible popup (the date picker a
page's showPicker() opened, a permission doorhanger) to that popup, so it
never reaches the renderer. Juggler waited 5 s per event for a renderer ack
that could not come: a click under the picker took 15 s and timed out
Playwright, and every input after it queued behind. Stock 158.0.1 Linux, by
OS (XTest) clicks on the same page: the clicks land on the picker at once, the
page sees none of them, the picker stays open. MouseDispatch._popupAt now
sends such an event without waiting for an ack.

Runs headless and, where Xvfb is installed, on a private Xvfb display.

    python browser/tests/playwright/patches/popup-covered-click.py
"""

import http.server
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# A private Xvfb display, started as playwright-window-size.py starts one.
_spec = importlib.util.spec_from_file_location(
    "playwright_window_size", Path(__file__).resolve().parent / "playwright-window-size.py")
_window_size = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_window_size)
xvfb = _window_size.xvfb

# The picker opens under a date input in the page's top-left corner and covers #t.
PAGE = """<!doctype html><html><body style="margin:0">
<button id="open" style="position:absolute;left:600px;top:400px;width:200px;height:40px">open</button>
<div id="t" style="position:absolute;left:60px;top:40px;width:200px;height:100px;background:#ccc">t</div>
<pre id="log" style="position:absolute;left:600px;top:500px"></pre>
<script>
const log = (m) => document.getElementById('log').append(m + ' ');
for (const k of ['mousedown', 'mouseup', 'click']) document.getElementById('t').addEventListener(k, () => log(k));
document.getElementById('open').addEventListener('click', () => {
  const d = document.createElement('input');
  d.type = 'date';
  document.body.prepend(d);
  try { d.showPicker(); log('picker'); } catch (e) { log('picker ' + e.name); }
});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE.encode())


def probe(binary, display):
    from camoufox.sync_api import Camoufox

    kw = dict(executable_path=str(binary), headless=display is None, os="linux", i_know_what_im_doing=True)
    if display:
        kw["env"] = {**os.environ, "DISPLAY": display}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with Camoufox(**kw) as browser:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{srv.server_port}/", wait_until="load")
        page.locator("#open").click()
        page.wait_for_timeout(1000)
        took = []
        for _ in range(2):
            t = time.monotonic()
            try:
                page.locator("#t").click(timeout=4000)
                took.append(round(time.monotonic() - t, 2))
            except Exception as e:
                took.append(type(e).__name__)
            page.wait_for_timeout(300)
        # The page's own log, read from the DOM: evaluate runs in an isolated world.
        out = {"took": took, "page": page.locator("#log").text_content().split()}
    srv.shutdown()
    return out


def main() -> int:
    binary = resolve_binary()
    failures, seen = [], {}
    proc, display = xvfb()
    try:
        for where in ("headless", display):
            if where is None:
                continue
            got = probe(binary, None if where == "headless" else where)
            seen[where] = got
            if got["page"][:1] != ["picker"]:
                failures.append(f"{where}: the picker did not open: {got['page']}")
            elif any(e in got["page"] for e in ("mousedown", "mouseup", "click")):
                failures.append(f"{where}: the page got the clicks, so no popup covered #t: {got['page']}")
            elif not all(isinstance(s, float) and s < 2 for s in got["took"]):
                failures.append(f"{where}: clicks under the picker took {got['took']}, want each under 2 s")
    finally:
        if proc:
            proc.kill()
            proc.wait()
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"PASS: clicks under an open popup go to it at once: {seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
