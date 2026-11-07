r"""
Input sent right after a navigation reaches the page whole, and no earlier than
a person's could.

Firefox's content process drops user input (wheel, keys, real mouse events)
that reaches a document before its input gate opens: 100 ms after readyState
became "loading" and three refresh ticks (dom.input_events.security.*,
PresShell::CanHandleUserInputEvents). Juggler's wheel is not flagged
synthesized-for-tests, so page.mouse.wheel(0, 300) straight after goto lost
its first notches: 2, 1 or 0 of 3 reached the page. Juggler's mouse and key
events are flagged, so they got through inside the
gate: a trusted pointermove 15 ms into the page, which no person's Firefox
delivers.

Now Juggler waits for the gate before it sends input. Over several fresh
pages, each driven the moment goto returns (move, click, key, wheel):

  - every wheel notch arrives: 3 for wheel(0, 300);
  - no trusted input event is stamped before domLoading + 100 ms.

    python browser/tests/playwright/patches/juggler-input-gate.py
"""

import http.server
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGES = 6
NOTCHES = 3  # wheel(0, 300): three notches of a line-mode wheel
GATE_MS = 100

PAGE = b"""<!doctype html><html><body style="height:5000px"><input id=t autofocus><script>
const seen = [];
const loading = performance.timing.domLoading - performance.timing.navigationStart;
for (const type of ['pointermove', 'mousemove', 'mousedown', 'click', 'keydown', 'wheel'])
  addEventListener(type, e => {
    if (!e.isTrusted) return;
    seen.push([type, e.timeStamp - loading]);
    document.body.dataset.seen = JSON.stringify(seen);
  }, true);
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


def main() -> int:
    from camoufox.sync_api import Camoufox

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    failures = []
    with Camoufox(headless=True, executable_path=str(resolve_binary()), os="linux", i_know_what_im_doing=True) as browser:
        for i in range(PAGES):
            page = browser.new_page()
            page.goto(f"{url}?{i}")
            page.mouse.move(200, 200)
            page.mouse.click(200, 200)
            page.keyboard.press("a")
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(1000)
            seen = json.loads(page.evaluate("() => document.body.dataset.seen || '[]'"))
            page.close()
            wheels = [t for kind, t in seen if kind == "wheel"]
            early = [(kind, round(t, 1)) for kind, t in seen if t < GATE_MS]
            print(f"page {i}: {len(wheels)} wheel events; first input at "
                  f"{min((t for _, t in seen), default=float('nan')):.1f} ms after loading; early={early}")
            if len(wheels) != NOTCHES:
                failures.append(f"page {i}: {len(wheels)} of {NOTCHES} wheel notches reached the page")
            if early:
                failures.append(f"page {i}: trusted input inside the {GATE_MS} ms input gate: {early}")
    server.shutdown()
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: input after goto arrives whole and after the input gate, as a person's does.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
