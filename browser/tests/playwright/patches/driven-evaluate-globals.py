"""
A driver's evaluate and locator calls define nothing on the page's window.

A window's WebIDL interfaces are defined on it lazily, the first time anything
needs one, and Object.getOwnPropertyNames(window) lists them in the order they
were defined. page.evaluate() and Playwright's locators run in an isolated
world, but the DOM objects they touch belong to the page: if wrapping one for
the isolated world defines its interface on the page's window, a page that
lists its globals after a driver read its DOM sees interfaces it never used.

The guard loads the same page twice under Playwright, once with only a
fill() and once after typical driver work (evaluate, query, locator reads,
the same fill, a screenshot), and has the page list its globals when told to. The lists must
match, and every interface the driver used must still work for the page.

    python browser/tests/playwright/patches/driven-evaluate-globals.py
"""

import difflib
import http.server
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGE_TIMEOUT_S = 60
# The page lists its globals when the driver changes the URL's fragment, so the
# driver never calls into the page to start it, and the page itself does
# nothing before then: no timers, no requests. It lists before it sends.
PAGE = (b"<!doctype html><html><head><title>t</title><script>"
        b"onhashchange = () => { const names = Object.getOwnPropertyNames(window);"
        b" const broken = names.filter(n => n !== 'undefined' && window[n] === undefined);"
        b" navigator.sendBeacon('/names', JSON.stringify({names, broken})); };"
        b"</script></head><body><div id='box' data-k='v' style='width:80px;height:20px'>some text</div>"
        b"<input id='in' style='position:absolute;left:200px;top:100px;width:100px;height:20px'><a href='#x' id='lnk'>link</a><table><tr><td>cell</td></tr></table>"
        b"<svg width='10' height='10'><rect width='5' height='5'/></svg></body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(PAGE, "text/html")

    def do_POST(self):
        self.server.names = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()
        self.server.arrived.set()


def work(page):
    """Typical driver calls that wrap page objects and interfaces."""
    page.evaluate("() => document.title")
    page.evaluate("() => ({count: document.querySelectorAll('*').length, title: document.title})")
    page.evaluate("() => document.querySelector('#in')")
    page.evaluate("v => v", {"a": [1, "x"]})
    handle = page.evaluate_handle("() => document.body")
    handle.json_value()
    handle.dispose()
    page.wait_for_selector("#box", state="attached")
    box = page.locator("#box")
    box.count()
    box.get_attribute("data-k")
    box.is_visible()
    box.bounding_box()
    box.text_content()
    page.locator("text=some text").count()
    page.locator("#lnk").inner_text()
    page.locator("td").all_inner_texts()
    page.locator("#in").fill("x")
    page.locator("#in").input_value()
    page.screenshot()


def same_input(page):
    """The input work() gives the page, without the driver's other reads.

    Whatever input fill() sends (a click on the field and keys, or focus and
    an insertText), the page receives it and Firefox's own actors define the
    interfaces of its events on the page's window as they do for a person's.
    The run left alone gets the same fill(), so the comparison sees only what
    the other reads add.
    """
    page.locator("#in").fill("x")


def globals_of(binary, server, url, driven):
    from camoufox.sync_api import Camoufox

    from camoufox import DefaultAddons

    server.arrived = threading.Event()
    # uBlock's content script runs when it likes, and wraps what it touches.
    # Reader mode's parse-on-load check does too: stock Firefox reads the
    # page's location and node geometry after the load's first paint
    # (AboutReaderChild -> Readerable.isProbablyReaderable), which defines
    # Location and DOMRectList on the page's window at whatever point the
    # input has reached by then. Off in both runs, so neither races the input.
    with Camoufox(executable_path=str(binary), headless=True, os="linux",
                  exclude_addons=[DefaultAddons.UBO],
                  firefox_user_prefs={"reader.parse-on-load.enabled": False}) as browser:
        page = browser.new_page()
        page.goto(url)
        if driven:
            work(page)
        else:
            same_input(page)
        page.goto(url + "#go")
        if not server.arrived.wait(PAGE_TIMEOUT_S):
            return None
        return server.names["names"], server.names["broken"]


def main() -> int:
    binary = resolve_binary()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        alone = globals_of(binary, server, url, False)
        driven = globals_of(binary, server, url, True)
    finally:
        server.shutdown()
    if alone is None or driven is None:
        print("FAIL: the page never reported its globals")
        return 1
    (alone, alone_broken), (driven, driven_broken) = alone, driven
    if driven_broken != alone_broken:
        print(f"FAIL: after driver work these globals read undefined: {driven_broken}")
        return 1
    print(f"{len(alone)} globals left alone, {len(driven)} after driver work")
    if alone == driven:
        print("PASS: driver work defines nothing on the page's window")
        return 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=alone, b=driven, autojunk=False).get_opcodes():
        if op != "equal":
            print(f"  {op}: alone {alone[i1:i2]} -> driven {driven[j1:j2]} near {alone[max(0, i1 - 3):i1 + 3]} / {driven[max(0, j1 - 3):j1 + 3]}")
    print("FAIL: the driver's work changes the page's globals")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
