"""
page.mouse.move() reaches the page as a real mouse's motion does in stock Firefox.

A real mouse reports faster than the refresh driver ticks. Stock Firefox
158.0.1 on Linux (GTK, X11) queues the moves in the content process and, at
each tick, dispatches one pointermove/mousemove that carries the queued ones
in getCoalescedEvents(), and a pointerrawupdate for each move as it arrives.
A 125 Hz XTest sweep on Xvfb (three runs, identical):
one pointermove per frame, 2 to 4 coalesced in each, a pointerrawupdate per
report.

Juggler's moves skipped the queue: one pointermove per move, a coalesced list
of length 1, as many pointermoves as pointerrawupdates. No mouse does that.

The guard moves along a 64-point path the way a script does
(page.mouse.move(x, y, steps=63)) and checks the page's counts. It also checks
that the page has the destination as soon as move() returns.

    python browser/tests/playwright/patches/driven-move-coalescing.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

# Served from 127.0.0.1: pointerrawupdate exists only in a secure context. The
# page records its own events and keeps them in an attribute for the driver.
PAGE = b"""<!doctype html><html><body style="margin:0;width:1200px;height:800px"><script>
  const moves = []; let raws = 0;
  const keep = () => document.body.dataset.seen = JSON.stringify([moves, raws]);
  addEventListener('pointermove', (e) => { moves.push([e.getCoalescedEvents().length, e.clientX, e.clientY]); keep(); }, true);
  addEventListener('pointerrawupdate', () => { raws++; keep(); }, true);
  addEventListener('keydown', () => { moves.length = 0; raws = 0; keep(); }, true);
</script></body></html>"""
SEEN = "() => JSON.parse(document.body.dataset.seen || '[[], 0]')"
STEPS = 63


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


def probe(binary):
    from camoufox.sync_api import Camoufox

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Camoufox(executable_path=str(binary), headless=False, os="linux", window=(1280, 900)) as browser:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
            page.mouse.move(100, 100)
            page.wait_for_timeout(300)
            page.keyboard.press("Shift")  # the page starts counting afresh
            page.mouse.move(100 + STEPS * 5, 100 + STEPS * 2, steps=STEPS)
            sweep = page.evaluate(SEEN)
            page.mouse.move(700, 500)
            last = page.evaluate(SEEN)[0][-1]
            return sweep, last
    finally:
        server.shutdown()


def main() -> int:
    with hidden_display("1920x1080"):
        (moves, raws), last = probe(resolve_binary())
    lens = [m[0] for m in moves] or [0]
    failures = []
    if raws != STEPS:
        failures.append(f"{raws} pointerrawupdate for {STEPS} moves: stock fires one per move")
    if sum(lens) != STEPS:
        failures.append(f"pointermoves carry {sum(lens)} coalesced moves, {STEPS} were made")
    if len(moves) > STEPS * 0.7:
        failures.append(f"{len(moves)} pointermoves for {STEPS} moves at 125 Hz: stock dispatches one per frame")
    if sorted(lens)[len(lens) // 2] < 2:
        failures.append(f"coalesced lengths {lens}: stock carries 2 to 4 per frame")
    if not moves or moves[-1][1:] != [100 + STEPS * 5, 100 + STEPS * 2]:
        failures.append(f"the page's last move is {moves[-1] if moves else None} when move() returned")
    if last[1:] != [700, 500]:
        failures.append(f"after move(700, 500) returned, the page's last move is {last}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: {STEPS} moves reach the page as {len(moves)} pointermoves, coalesced {min(lens)}-{max(lens)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
