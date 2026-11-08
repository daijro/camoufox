"""A driven page stays focused and visible, as Camoufox intends.

This is deliberately not stock. Upstream Playwright's Juggler set
docShell.overrideHasFocus and docShell.forceActiveState on every top-level
document, so every page of a driven browser reads as focused and visible,
whatever is in front of it. Camoufox keeps that behaviour for the product:
a caller's pages must keep running as if a person is looking at each one.
The deviation is page-visible (see
ci/tribal-rules.yml, driven-pages-stay-focused).

The page records what it sees in its DOM (a driver's evaluate runs in an
isolated world), and the guard checks that it stayed focused in both cases.
The driver then types into the page behind: the keydowns must find
document.hasFocus() true, as they do for a person's focused page.

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

    # A driven page keeps focus and visibility, even when another page is in
    # front, and keyboard input reaches it without raising its window first.
    for name, state in (("behind another window", window), ("behind a foreground tab", tab)):
        if not state["hasFocus"]:
            failures.append(f"{name}: document.hasFocus() is false (Camoufox keeps it true)")
        if state["visibility"] != "visible":
            failures.append(f"{name}: visibilityState {state['visibility']} (Camoufox keeps it visible)")
    if window["keys"] != "FFF":
        failures.append(f"behind another window: keydowns saw hasFocus() {window['keys']!r} "
                        "(F true, U false; Camoufox delivers them as a focused page)")

    for f in failures:
        print("  " + f)
    if failures:
        print("FAIL: a driven page in the background lost focus or visibility")
        return 1
    print("PASS: a driven page stays focused and visible behind another page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
