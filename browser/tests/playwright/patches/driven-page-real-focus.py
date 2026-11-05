"""
A driven page in the background loses focus and visibility as in stock.

Upstream Playwright's Juggler set docShell.overrideHasFocus and
docShell.forceActiveState on every top-level document
(juggler/content/main.js), so every page of a driven browser read as the
focused, visible page whatever was in front of it. Measured 2026-11-01 on
Linux, stock Firefox 158.0.1 (no driver) against Playwright-driven camoufox,
headless and headed (Xvfb + openbox), 3 launches each, every run alike:

- a page behind a second page's window (context.new_page()) or behind a
  window.open() popup window: stock document.hasFocus() false, `blur` on the
  focused element, then on the document and the window; driven hasFocus()
  true while :-moz-window-inactive matched, and no document or window blur.
- a page behind a foreground tab its own window.open() opened: stock
  visibilityState "hidden" after a visibilitychange, hasFocus() false, rAF
  and a 10 ms setInterval both down to ~1 a second; driven "visible", no
  visibilitychange, rAF at 60 Hz and the interval unthrottled.

The page records what it sees in its DOM (a driver's evaluate runs in an
isolated world), and the guard checks the stock outcome in both cases. Then
the driver types into the page behind: the OS gives keys only to the active
window, so each keydown must find document.hasFocus() true (Juggler brings
the page to the front first, as the mouse already did).

    python browser/tests/playwright/patches/driven-page-real-focus.py
"""

import http.server
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

# The page logs focus, blur and visibility events into data-ev on <html>.
PAGE = (b"<!doctype html><html><head><title>t</title></head><body><input id=in><script>"
        b"const log = e => { const d = document.documentElement;"
        b" const t = e.target === window ? 'window' : e.target === document ? 'document' : e.target.id;"
        b" d.dataset.ev = (d.dataset.ev || '') + e.type + ':' + t + ' '; };"
        b"for (const t of ['focus', 'blur']) addEventListener(t, log, true);"
        b"document.addEventListener('visibilitychange', log, true);"
        b"addEventListener('keydown', e => { const d = document.documentElement;"
        b" d.dataset.keys = (d.dataset.keys || '') + (document.hasFocus() ? 'F' : 'U'); }, true);"
        b"addEventListener('load', () => document.getElementById('in').focus());"
        b"</script></body></html>")

READ = """() => {
  let raf = 0, ticks = 0;
  const f = () => { raf++; requestAnimationFrame(f); };
  requestAnimationFrame(f);
  const id = setInterval(() => ticks++, 10);
  return new Promise(r => setTimeout(() => { clearInterval(id); r({
    hasFocus: document.hasFocus(), visibility: document.visibilityState,
    events: (document.documentElement.dataset.ev || '').trim(), raf, ticks}); }, 1500));
}"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(PAGE)


def settle(page):
    """Wait until the page's input has its focus event, so later blurs are the scenario's."""
    page.wait_for_function("() => (document.documentElement.dataset.ev || '').includes('focus:in')")


def behind_window(browser, url):
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    settle(page)
    front = context.new_page()
    front.goto(url)
    settle(front)
    time.sleep(0.5)
    state = page.evaluate(READ)
    # Keys a driver types into the page behind reach it as a person's would:
    # with its window in front, so never while document.hasFocus() is false.
    page.keyboard.type("abc")
    state["keys"] = page.evaluate("() => document.documentElement.dataset.keys || ''")
    context.close()
    return state


def behind_tab(browser, url):
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    settle(page)
    with page.expect_popup() as popup:
        page.evaluate("u => { window.open(u); }", url)
    popup.value.wait_for_load_state()
    time.sleep(0.5)
    state = page.evaluate(READ)
    context.close()
    return state


def main() -> int:
    from camoufox.sync_api import Camoufox

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    failures = []
    try:
        with Camoufox(**launch_kwargs(os="linux")) as browser:
            window = behind_window(browser, url)
            tab = behind_tab(browser, url)
    finally:
        server.shutdown()
    print("behind another window:", json.dumps(window))
    print("behind a foreground tab:", json.dumps(tab))

    # Stock: the page lost the focus, and the document and window heard it.
    for name, state in (("behind another window", window), ("behind a foreground tab", tab)):
        if state["hasFocus"]:
            failures.append(f"{name}: document.hasFocus() is true (stock: false)")
        for blur in ("blur:in", "blur:document", "blur:window"):
            if blur not in state["events"].split():
                failures.append(f"{name}: no {blur} event (stock fires it)")
    # Stock: a window behind another still renders; a background tab is hidden and throttled.
    if window["keys"] != "FFF":
        failures.append(f"behind another window: keydowns saw hasFocus() {window['keys']!r} "
                        "(F true, U false; stock delivers keys only to the focused window)")
    if window["visibility"] != "visible":
        failures.append(f"behind another window: visibilityState {window['visibility']} (stock: visible)")
    if tab["visibility"] != "hidden" or "visibilitychange:document" not in tab["events"].split():
        failures.append(f"behind a foreground tab: visibilityState {tab['visibility']}, events "
                        f"{tab['events']!r} (stock: hidden after a visibilitychange)")
    if tab["raf"] > 10 or tab["ticks"] > 20:
        failures.append(f"behind a foreground tab: {tab['raf']} frames and {tab['ticks']} 10 ms ticks in "
                        "1.5 s (stock throttles both to about one a second)")

    for f in failures:
        print("  " + f)
    if failures:
        print("FAIL: a driven page in the background reads as focused or visible")
        return 1
    print("PASS: a driven page in the background loses focus and visibility as in stock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
