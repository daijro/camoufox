"""
A Playwright drag under a Windows identity reaches the page in Windows' order.

On Windows the move that starts a drag is followed by DoDragDrop's modal OLE
loop. The move queued behind it stays in the window's message queue for the
whole drag, and the page gets it only after dragend: a pointermove/mousemove
at that earlier point, the button still held, movement from the move before
it, and the timestamp it was made at (~470 ms before dragend). A move at the
drop point with the button released follows, its movement counted from that
deferred point, and the next move counts from the drop point. Nothing leaves
the window around the drag: no mouseleave up to the root. The
drag's first motion is the move after the deferred one, so the first dragenter
is the target's. Measured on win-i9, stock Firefox 158.0.1, SendInput, three
runs (cfparity it4 drag, identical).

Juggler emulates GTK's drag session for every identity: the move after
dragstart arrives as a held mousemove at once, the next motion takes the
pointer out of the window (a widget exit), and the move after the drop reports
no movement.

The guard drives the cfparity driven.drag path through Playwright, claiming
Windows, and compares the page's moves and drag events with stock Windows'.
The deferred move's timestamp needs the browser change that lets Juggler
backdate an event (jugglerSendMouseEvent's ageMs).

    python browser/tests/playwright/patches/windows-drag-deferred-move.py
"""

import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

STEP = 0.05
PAGE = b"""<!doctype html><html><body style="margin:0">
<div id="stage" style="position:absolute;left:0;top:0;width:800px;height:600px">
<div id="src" draggable="true" style="position:absolute;left:40px;top:180px;width:81px;height:41px;background:#cde"></div>
<div id="dst" style="position:absolute;left:280px;top:210px;width:81px;height:41px;background:#edc"></div>
</div></body></html>"""
TYPES = ["dragstart", "drag", "dragenter", "dragover", "dragleave", "drop", "dragend",
         "pointerdown", "pointermove", "pointerup", "pointercancel", "pointerleave",
         "mousedown", "mousemove", "mouseup", "mouseleave"]
RECORD = """(types) => {
  window.__events = [];
  const who = (t) => t ? (t.id || t.nodeName.toLowerCase()) : null;
  let last = null;
  const on = (e) => {
    // drag and dragover repeat on a timer while the pointer rests; a run counts once.
    const repeat = (e.type === 'drag' || e.type === 'dragover') && last && last[0] === e.type;
    if (repeat) return;
    last = [e.type, who(e.target), e.buttons, who(e.relatedTarget), e.movementX, e.movementY, e.timeStamp];
    window.__events.push(last);
  };
  for (const t of types) window.addEventListener(t, on, true);
  const accept = (e) => e.preventDefault();
  document.getElementById('dst').addEventListener('dragover', accept);
  document.getElementById('dst').addEventListener('drop', accept);
  document.getElementById('src').addEventListener('dragstart', (e) => e.dataTransfer.setData('text/plain', 'x'));
}"""

# win-i9, stock 158.0.1 (type, target, buttons, movement for moves), drag/dragover runs counted once
M = None
WINDOWS = [
    ("pointermove", "src", 0, M), ("mousemove", "src", 0, M),
    ("pointerdown", "src", 1, M), ("mousedown", "src", 1, M),
    ("dragstart", "src", 1, M), ("pointercancel", "src", 1, M), ("mousemove", "src", 1, (0, 0)),
    ("drag", "src", 0, M), ("dragenter", "dst", 1, M), ("dragover", "dst", 1, M),
    ("drag", "src", 0, M), ("dragover", "dst", 1, M),
    ("drop", "dst", 0, M), ("dragend", "src", 0, M),
    ("pointermove", "src", 1, (20, 5)), ("mousemove", "src", 1, (20, 5)),
    ("pointermove", "dst", 0, (210, 20)), ("mousemove", "dst", 0, (210, 20)),
    ("pointermove", "stage", 0, (300, 170)), ("mousemove", "stage", 0, (300, 170)),
]


def drive(page):
    """cfparity's driven.drag path: src centre, held, three moves, the target, released, away."""
    steps = [("move", 80, 200), ("down",), ("move", 90, 205), ("move", 110, 210),
             ("move", 300, 230), ("wait", 0.2), ("move", 320, 230), ("wait", 0.2), ("up",), ("move", 620, 400)]
    for step in steps:
        if step[0] == "move":
            page.mouse.move(step[1], step[2])
        elif step[0] == "down":
            page.mouse.down()
        elif step[0] == "up":
            page.mouse.up()
        else:
            time.sleep(step[1])
        time.sleep(STEP)
    time.sleep(0.5)


def probe(binary):
    from camoufox.sync_api import Camoufox

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with Camoufox(executable_path=str(binary), headless=False, os="windows", window=(1280, 900),
                  i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
        page.mouse.move(400, 300)
        time.sleep(0.3)
        page.evaluate(RECORD, TYPES)
        drive(page)
        events = page.evaluate("window.__events")
    server.shutdown()
    return events


def project(events):
    """Leave events out (checked on their own); moves keep their movement."""
    out = []
    for e in events:
        if e[0] in ("pointerleave", "mouseleave"):
            continue
        moved = tuple(e[4:6]) if e[0] in ("pointermove", "mousemove") and out and out[-1][0] != "pointerup" else M
        out.append((e[0], e[1], e[2], moved))
    # the first move's movement depends on where the pointer was before recording
    return [(t, w, b, M) if i < 2 else (t, w, b, m) for i, (t, w, b, m) in enumerate(out)]


def main() -> int:
    with hidden_display("1920x1080"):
        events = probe(resolve_binary())
    got = project(events)
    if "-v" in sys.argv:
        for e in events:
            print("   ", e)
    failures = []
    if got != WINDOWS:
        import difflib
        for line in difflib.unified_diff([str(e) for e in WINDOWS], [str(e) for e in got],
                                         "stock windows", "driven", lineterm="", n=1):
            print("  " + line)
        failures.append("the drag's moves and drag events differ from stock Windows'")
    # A widget exit is a mouseleave at the root with no relatedTarget. (The pointerleave chain after
    # pointercancel is the spec's, on every platform; stock GTK has it before its exit too.)
    exits = [e for e in events if e[0] == "mouseleave" and e[1] == "html" and e[3] is None]
    if exits:
        failures.append("the pointer left the window during the drag (a mouseleave at the root); "
                        "stock Windows has none")
    end = next((e for e in events if e[0] == "dragend"), None)
    held = [e for e in events if e[0] == "mousemove" and e[2] == 1]
    deferred = held[-1] if held else None
    if end and deferred and events.index(deferred) > events.index(end):
        age = end[6] - deferred[6]
        print(f"  deferred move stamped {age:.0f} ms before dragend (stock ~470)")
        if age < 300:
            failures.append(f"the deferred move is stamped {age:.0f} ms before dragend; stock stamps it when it was "
                            "made, ~470 ms before")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a Playwright drag claiming Windows reaches the page in Windows' order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
