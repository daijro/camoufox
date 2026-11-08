"""
A Playwright drag on Linux reaches the page the way an OS drag does in stock Firefox.

On GTK a drag session does not take the pointer at once. The move after the
one that fires dragstart still arrives as a mousemove with the button held;
the session takes over on the move after that, and taking the pointer away
from the window is a widget exit: pointerout/pointerleave and mouseout/
mouseleave up to the root, relatedTarget null, which also forgets the
reference point mouse movement is measured from. Only then do dragenter and
dragover start, with nothing hovered, so dragenter has no relatedTarget and no
dragleave fires for the source. After the drop and dragend the pointer comes
back as a widget enter at the drop point, and the next move reports no
movement. Measured with the drag below as XTest input (stock 158.0.1 on Xvfb,
three runs, identical).

Juggler's emulated drag sent dragover from the first move after dragstart,
never left the window, and so fired dragenter and dragleave on the source,
dragenter on the target with the source as relatedTarget, hover events
carrying the held button after dragend, and a movement on the next move that
spanned the whole drag.

The source gets a `drag` event with each motion of the drag, before the
target's dragover, as GTK's drag session fires it (buttons 0); the dragover
GTK sends before a drop is not a motion and has none. The pointercancel that
ends the pointer stream at dragstart carries one coalesced event, the move
that started the drag, which reaches the page coalesced like a real one.

One thing is not compared: the order of the two hover chains at the drop
point. Stock's mouseover/mouseenter (button held) come before its
pointerover/pointerenter (released); Juggler's arrive pointer first. Each
chain is compared in its own order.

The guard drives the same drag through Playwright on a hidden X display, and compares the page's event stream with stock's.

    python browser/tests/playwright/patches/driven-drag-gtk.py
"""

import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

STEP = 0.05
# Served from 127.0.0.1: getCoalescedEvents() exists only in a secure context.
PAGE = b"""<!doctype html><html><body style="margin:0">
<div id="stage" style="position:absolute;left:0;top:0;width:800px;height:600px">
<div id="src" draggable="true" style="position:absolute;left:40px;top:180px;width:81px;height:41px;background:#cde"></div>
<div id="dst" style="position:absolute;left:280px;top:210px;width:81px;height:41px;background:#edc"></div>
</div></body></html>"""
TYPES = ["dragstart", "drag", "dragenter", "dragover", "dragleave", "drop", "dragend",
         "pointerover", "pointerenter", "pointerdown", "pointermove", "pointerup", "pointerout",
         "pointerleave", "pointercancel", "mouseover", "mouseenter", "mousedown", "mousemove",
         "mouseup", "mouseout", "mouseleave", "click"]
RECORD = """(types) => {
  window.__events = [];
  const who = (t) => t ? (t.id || t.nodeName.toLowerCase()) : null;
  let sawDragover = false;
  const on = (e) => {
    // dragover repeats, on a timer and with each motion's drag; a run of
    // them counts once.
    if (e.type === 'dragover' && sawDragover) return;
    if (e.type !== 'drag') sawDragover = e.type === 'dragover';
    window.__events.push([e.type, who(e.target), e.buttons, who(e.relatedTarget), e.movementX, e.movementY,
                          e.getCoalescedEvents ? e.getCoalescedEvents().length : null]);
  };
  for (const t of types) window.addEventListener(t, on, true);
  const accept = (e) => e.preventDefault();
  document.getElementById('dst').addEventListener('dragover', accept);
  document.getElementById('dst').addEventListener('drop', accept);
  document.getElementById('src').addEventListener('dragstart', (e) => e.dataTransfer.setData('text/plain', 'x'));
}"""

# stock 158.0.1, GTK/X11, the drag below as XTest input
H = "html"
B = "body"
S = "stage"
STOCK = [
    ("pointerout", S, 0, "src"), ("pointerover", "src", 0, S), ("pointerenter", "src", 0, S),
    ("pointermove", "src", 0, None),
    ("mouseout", S, 0, "src"), ("mouseover", "src", 0, S), ("mouseenter", "src", 0, S),
    ("mousemove", "src", 0, None),
    ("pointerdown", "src", 1, None), ("mousedown", "src", 1, None),
    ("dragstart", "src", 1, None),
    ("pointercancel", "src", 1, None),
    ("pointerout", "src", 1, None), ("pointerleave", "src", 1, None), ("pointerleave", S, 1, None),
    ("pointerleave", B, 1, None), ("pointerleave", H, 1, None),
    ("pointerover", "src", 1, None), ("pointerenter", H, 1, None), ("pointerenter", B, 1, None),
    ("pointerenter", S, 1, None), ("pointerenter", "src", 1, None),
    ("mousemove", "src", 1, None),
    ("pointermove", "src", 1, None), ("mousemove", "src", 1, None),
    ("pointerout", "src", 1, None), ("pointerleave", "src", 1, None), ("pointerleave", S, 1, None),
    ("pointerleave", B, 1, None), ("pointerleave", H, 1, None),
    ("mouseout", "src", 1, None), ("mouseleave", "src", 1, None), ("mouseleave", S, 1, None),
    ("mouseleave", B, 1, None), ("mouseleave", H, 1, None),
    ("drag", "src", 0, None), ("dragenter", "dst", 1, None), ("dragover", "dst", 1, None),
    ("drag", "src", 0, None), ("drop", "dst", 0, None), ("dragend", "src", 0, None),
    ("mouseover", "dst", 1, None), ("mouseenter", H, 1, None), ("mouseenter", B, 1, None),
    ("mouseenter", S, 1, None), ("mouseenter", "dst", 1, None),
    ("pointerover", "dst", 0, None), ("pointerenter", H, 0, None), ("pointerenter", B, 0, None),
    ("pointerenter", S, 0, None), ("pointerenter", "dst", 0, None),
    ("pointerout", "dst", 0, S), ("pointerleave", "dst", 0, S), ("pointerover", S, 0, "dst"),
    ("pointermove", S, 0, None),
    ("mouseout", "dst", 0, S), ("mouseleave", "dst", 0, S), ("mouseover", S, 0, "dst"),
    ("mousemove", S, 0, None),
]


def drive(page):
    """The drag: src centre, held, three moves, the target, released, home."""
    steps = [("move", 400, 300), ("move", 80, 200), ("down",), ("move", 90, 205), ("move", 110, 210),
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
    with Camoufox(executable_path=str(binary), headless=False, os="linux", window=(1280, 900)) as browser:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
        page.mouse.move(400, 300)
        time.sleep(0.3)
        page.evaluate(RECORD, TYPES)
        drive(page)
        events = page.evaluate("window.__events")
    server.shutdown()
    return events


def after_drop(events):
    """The hover chains after dragend, mouse events first, each in its own order."""
    end = next(i for i, e in enumerate(events) if e[0] == "dragend") + 1
    stop = next(i for i in range(end, len(events)) if events[i][3] is not None)
    chain = events[end:stop]
    mouse = [e for e in chain if e[0].startswith("mouse")]
    return events[:end] + mouse + [e for e in chain if e not in mouse] + events[stop:]


def main() -> int:
    with hidden_display("1920x1080"):
        events = probe(resolve_binary())
    got = after_drop([tuple(e[:4]) for e in events])
    failures = []
    if got != STOCK:
        import difflib
        for line in difflib.unified_diff([str(e) for e in STOCK], [str(e) for e in got],
                                         "stock", "driven", lineterm="", n=1):
            print("  " + line)
        failures.append("the drag's event stream differs from stock's")
    cancel = [e[6] for e in events if e[0] == "pointercancel"]
    if cancel != [1]:
        failures.append(f"pointercancel carries {cancel} coalesced events, stock [1]")
    last_move = [e for e in events if e[0] == "mousemove"][-1]
    if last_move[4:6] != [0, 0]:
        failures.append(f"the first move after the drop reports movement {last_move[4:6]}, stock [0, 0]")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a Playwright drag reaches the page as a GTK drag does in stock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
