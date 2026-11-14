"""
Page code that a driver call runs sees only its own frames in a stack.

Every callFunction reaches the page through ExecutionContext.evaluateFunction
(content/Runtime.js): the `mw:` evaluate, and the isolated world's utility
script, whose focus(), click() and dispatchEvent() run page listeners
synchronously. It used to call through Debugger.Object.apply, which
0-playwright.patch runs with every JS security callback cleared to lift CSP.
That included subsumes, which the engine asks before it puts another
principal's frame into a stack a page reads. So a page that hooked an API and
read `new Error().stack` when it was called got the isolated world's frames
(focusNode, dispatchEvent, evaluate) and Juggler's own
(resource://gre/modules/juggler/content/Runtime.js, SimpleChannel.js,
withDriverPopups). Akamai Page Integrity Manager hooks DOM and network APIs this
way and sends those strings home. The call is now made from Debugger-compiled
code with bypassCSP, which lifts CSP alone.

What PASS means: for each driver call below, the hook recorded a stack, and
every frame in it is the page's own. A `mw:` evaluate's code runs in the page
as Debugger-compiled script, so its frames are "debugger eval code"; nothing
may follow them. A focus or dispatch from the isolated world shows only the
page's listener, as it does for a person.

    python browser/tests/playwright/patches/driver-stack-frames.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

PAGE = b"""<!doctype html><button id="b">b</button><input id="i"><script>
window.stacks = [];
const querySelector = Document.prototype.querySelector;
Document.prototype.querySelector = function (selector) {
  window.stacks.push(new Error().stack);
  return querySelector.call(this, selector);
};
document.getElementById('b').addEventListener('click', () => document.querySelector('#b'));
document.getElementById('i').addEventListener('focus', () => document.querySelector('#i'));
</script>"""

DEBUGGER_EVAL = "debugger eval code"

# (label, driver call, whether the page runs code the driver compiled)
CALLS = (
    ("mw: evaluate", lambda page: page.evaluate("mw:document.querySelector('#b')"), True),
    ("isolated evaluate el.click()", lambda page: page.evaluate("document.querySelector('#b').click()"), False),
    ("page.dispatch_event", lambda page: page.dispatch_event("#b", "click"), False),
    ("page.focus", lambda page: page.focus("#i"), False),
)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


def foreign_frames(stack, url, driver_code):
    frames = [line.rsplit("@", 1)[-1] for line in stack.splitlines() if line]
    return [f for f in frames if not f.startswith(url) and not (driver_code and f.startswith(DEBUGGER_EVAL))]


def main() -> int:
    from camoufox.sync_api import Camoufox

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    failures = []
    try:
        with Camoufox(**launch_kwargs(os="linux", main_world_eval=True, i_know_what_im_doing=True)) as browser:
            page = browser.new_page()
            page.goto(url, wait_until="load")
            for label, call, driver_code in CALLS:
                call(page)
                stacks = page.evaluate("mw:window.stacks.splice(0)")
                if not stacks:
                    failures.append(f"{label}: the page's hook never ran")
                    continue
                foreign = [f for s in stacks for f in foreign_frames(s, url, driver_code)]
                if foreign:
                    failures.append(f"{label}: the page's stack shows {foreign}")
                else:
                    print(f"PASS: {label}: {stacks[0].splitlines()}")
    finally:
        srv.shutdown()
    for f in failures:
        print(f"FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
