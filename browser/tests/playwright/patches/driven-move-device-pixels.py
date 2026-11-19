"""
A driven pointer at a display scale above 1 moves in device pixels, as a mouse does.

Playwright floors every Firefox mouse coordinate to a whole CSS pixel before it
sends it. A Windows mouse at scale 2.5 (stock 159.0, a person's recording) moves
in device pixels: 78% of its pointermoves have a fractional clientX, and 10.7%
of its mousemoves have no movement, the sub-pixel steps that stay inside one
CSS pixel. At scale 1 it has neither, and Windows never repeats an exact position. A
driven pointer had neither at any scale. A macOS mouse reports whole CSS
pixels (0% fractional at scale 2), so a macOS identity keeps them, and it
repeats them: 19% of its pointermoves and mousemoves are at the position before.

The guard sweeps a path at scale 2.5 under a Windows identity and checks:
- that every pointermove sits on a device pixel inside the CSS pixel asked for;
- that most are fractional, and not all;
- that repeated moves to one CSS pixel move within it;
- that a press lands where the pointer is.
Under a macOS identity at scale 2 it checks that every clientX is whole, and
that repeated moves to one point reach the page as exact repeats.

    python browser/tests/playwright/patches/driven-move-device-pixels.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = b"""<!doctype html><html><body style="margin:0;width:1200px;height:800px"><script>
  const seen = [];
  const keep = () => document.body.dataset.seen = JSON.stringify(seen);
  for (const type of ['pointermove', 'mousemove', 'pointerdown'])
    addEventListener(type, (e) => { seen.push([type, e.clientX, e.clientY, e.movementX, e.movementY]); keep(); }, true);
  addEventListener('keydown', () => { seen.length = 0; keep(); }, true);
</script></body></html>"""
SEEN = "() => JSON.parse(document.body.dataset.seen || '[]')"
SWEEP = [(40 + i * 3, 40 + i) for i in range(120)]
STILL = (300, 150)
REPEATS = 20


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


def probe(binary, os_name, dpr):
    from camoufox.sync_api import Camoufox

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with Camoufox(executable_path=str(binary), headless=False, os=os_name, window=(600, 380),
                      config={"window.devicePixelRatio": dpr}, i_know_what_im_doing=True) as browser:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
            page.mouse.move(20, 20)
            page.wait_for_timeout(300)
            page.keyboard.press("Shift")  # the page starts counting afresh
            for x, y in SWEEP:
                page.mouse.move(x, y)
            sweep = page.evaluate(SEEN)
            page.keyboard.press("Shift")
            for _ in range(REPEATS):
                page.mouse.move(*STILL)
            page.mouse.down()
            page.mouse.up()
            page.wait_for_timeout(100)
            return sweep, page.evaluate(SEEN)
    finally:
        server.shutdown()


def on_device_pixel(v, dpr):
    return abs(v * dpr - round(v * dpr)) < 1e-3


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        sweep, still = probe(resolve_binary(), "windows", 2.5)
        mac_sweep, mac_still = probe(resolve_binary(), "macos", 2)

    asked = set(SWEEP)
    moves = [e for e in sweep if e[0] == "pointermove"]
    stray = [e for e in moves if (int(e[1] // 1), int(e[2] // 1)) not in asked
             or not (on_device_pixel(e[1], 2.5) and on_device_pixel(e[2], 2.5))]
    if stray:
        failures.append(f"pointermoves off a device pixel of the CSS pixel asked for: {stray[:5]}")
    frac = sum(1 for e in moves if e[1] != int(e[1])) / max(1, len(moves))
    # A device pixel on a CSS pixel's edge is whole, so some moves are.
    if not 0.6 <= frac < 1:
        failures.append(f"{frac:.0%} of pointermoves have a fractional clientX at 2.5; a mouse there has 78%")

    here = [e for e in still if e[0] == "pointermove"]
    if len(here) < 2 or any((int(e[1]), int(e[2])) != STILL for e in here):
        failures.append(f"{REPEATS} moves to {STILL} reached the page as {here}: a hand moves within the pixel")
    if not any(e[0] == "mousemove" and e[3] == 0 and e[4] == 0 for e in still):
        failures.append("no mousemove without movement: sub-pixel steps give them on a real mouse")
    downs = [e for e in still if e[0] == "pointerdown"]
    if not downs or not here or downs[0][1:3] != here[-1][1:3]:
        failures.append(f"pointerdown at {downs[0][1:3] if downs else None}, the pointer at {here[-1][1:3] if here else None}")

    mac = [e for e in mac_sweep if e[0] == "pointermove"]
    if not mac or any(e[1] != int(e[1]) or e[2] != int(e[2]) for e in mac):
        failures.append(f"a macOS identity's pointermoves are fractional: {[e for e in mac if e[1] != int(e[1])][:5]}")

    for kind in ("pointermove", "mousemove"):
        repeats = [e for e in mac_still if e[0] == kind]
        # Moves sent within one frame coalesce, so fewer than REPEATS arrive.
        if len(repeats) < 2 or any(e[1:] != [*STILL, 0, 0] for e in repeats[1:]):
            failures.append(f"{REPEATS} macOS moves to {STILL} reached the page as {repeats}: "
                            f"a Mac repeats the position")

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: {frac:.0%} of {len(moves)} pointermoves fractional at 2.5, whole under macOS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
