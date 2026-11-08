"""
A main-world evaluate resolves no page global the evaluated script does not name.

The page's own global keeps its lazily created standard classes in the order the
page first used them, and Object.getOwnPropertyNames(window) lists them in that
order. The `mw:` wrapper (content/Runtime.js mainWorldEvaluate) named eleven typed
array constructors, NaN and Infinity (which bring Number, isNaN, parseInt...),
Error, Date, URL and Array in the page, and the main world's stringify wrapper
named JSON, Date and Array there, so the first `mw:` evaluate resolved all of
them. Typed arrays and the others are now told by internal class, and the
result is read through Debugger instead of the page's JSON.stringify.

Two tabs load the same page, which reads its own global order once it has
settled; only one gets `mw:() => 1` before that. The names the wrapper used to
resolve must stand in the same order in both. Other names are left out: two
untouched tabs already differ there (XMLHttpRequest, JSON, Location,
DOMRectList: tab setup and timing, not the evaluate).

A third tab gets what a scraper evaluates in the main world: querySelectorAll,
getElementsByTagName, querySelector. The DOM objects that creates (a NodeList,
an HTMLCollection, an HTMLPreElement) defined their interfaces on the window
then, before the page used them, because Juggler's main-world code runs in the
page's realm as Debugger code and was taken for the page's own (NodeList
about 30 names early). It is Juggler's, as
an isolated world's is: those interfaces must stand where the untouched tab has
them. It is compared with an untouched tab opened just before it, not the
first: the first tab of a browser places HTMLCollection differently from every
later one with no evaluate at all (measured 2026-11-04: 415 vs ~944).

    python browser/tests/playwright/patches/main-world-eval-globals.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGE = b"""<!doctype html><title>g</title><pre id="o"></pre><script>
setTimeout(() => {
  const keys = Object.getOwnPropertyNames(window);
  document.getElementById('o').textContent = JSON.stringify({
    order: keys,
    int16: Object.getOwnPropertyNames(Int16Array).join(','),
  });
}, 1500);
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


def probe(binary):
    import json
    from camoufox.sync_api import Camoufox

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    out = {}
    try:
        with Camoufox(executable_path=str(binary), headless=True, os="linux", main_world_eval=True,
                      i_know_what_im_doing=True) as browser:
            for name in ("plain", "mw", "plain2", "scrape"):
                page = browser.new_page()
                page.goto(url, wait_until="load")
                if name == "mw":
                    page.evaluate("mw:() => 1")
                elif name == "scrape":
                    page.evaluate(SCRAPE)
                out[name] = json.loads(page.locator("#o:not(:empty)").text_content(timeout=10000))
    finally:
        srv.shutdown()
    return out


# What mainWorldEvaluate and its result path could resolve in the page, minus JSON
# (moves between two untouched tabs too).
WATCHED = ("Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array",
           "Float16Array", "Float32Array", "Float64Array", "BigInt64Array", "BigUint64Array", "Number", "NaN",
           "Infinity", "isNaN", "isFinite", "parseInt", "parseFloat", "Error", "Date", "URL", "RegExp", "Array")


# A scraper's main-world read, and the interfaces of what it creates.
SCRAPE = ("mw:() => [document.querySelectorAll('*').length, document.getElementsByTagName('pre').length, "
          "document.querySelector('pre').id, document.title]")
SCRAPED = ("NodeList", "HTMLCollection", "HTMLPreElement")


def watched(order, names=WATCHED):
    return [n for n in order if n in names]


def moved(a, b):
    import difflib
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [b[j1:j2] or a[i1:i2] for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]


def main() -> int:
    r = probe(resolve_binary())
    failures = []
    diff = moved(watched(r["plain"]["order"]), watched(r["mw"]["order"]))
    if diff:
        failures.append(f"global order moved by one mw: evaluate: {diff}")
    # Among the standard classes, which stand still between untouched tabs: the untouched tab
    # defines the scraped interfaces only when it enumerates, after them.
    names = WATCHED + SCRAPED
    diff = moved(watched(r["plain2"]["order"], names), watched(r["scrape"]["order"], names))
    if diff:
        failures.append(f"global order moved by a main-world DOM read (the driver's objects defined their "
                        f"interfaces on the window): {diff}")
    if r["plain"]["int16"] != r["mw"]["int16"]:
        failures.append(f"Int16Array own keys {r['mw']['int16']!r}, untouched page {r['plain']['int16']!r}")
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"PASS: a mw: evaluate leaves the page's globals as they were ({len(r['mw']['order'])} names)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
