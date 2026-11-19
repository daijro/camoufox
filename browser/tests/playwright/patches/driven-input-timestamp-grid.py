"""
Driven input under a Windows identity is stamped on the Windows system tick.

Windows stamps each input message with its tick count (GetMessageTime): whole
milliseconds that advance in steps of 15.625 ms. People's recordings on stock
159.0 (private, a mouse and a touchpad) put every gap between pointermoves,
keydowns and mouse wheel events on that grid: 15, 16, 31, 32, 47 ms and so
on. macOS stamps input from a high-resolution clock, as a driven event
always was.

The guard moves, types and wheels under a Windows identity and checks that
every gap between two input events is a whole number of milliseconds that a
run of 15.625 ms ticks can span. Gaps are taken within the mouse and wheel
events, which the parent process stamps, and within the keys, which the
content process stamps. Under a macOS identity it checks that most gaps are
not on the tick.

    python browser/tests/playwright/patches/driven-input-timestamp-grid.py
"""

import http.server
import math
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = b"""<!doctype html><html><body style="margin:0;height:3000px">
<input id="field" style="margin:200px"><script>
  const seen = [];
  for (const type of ['pointermove', 'pointerdown', 'pointerup', 'keydown', 'keyup', 'wheel'])
    addEventListener(type, (e) => {
      for (const c of (type === 'pointermove' ? e.getCoalescedEvents() : [e])) seen.push([type, c.timeStamp]);
      document.body.dataset.seen = JSON.stringify(seen);
    }, true);
</script></body></html>"""
TICK = 15.625


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)


def on_grid(gap):
    whole = round(gap)
    if abs(gap - whole) > 0.05:
        return False
    k = round(whole / TICK)
    return whole in {math.floor(k * TICK), math.ceil(k * TICK)}


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    # getCoalescedEvents() needs a secure context, which a loopback http page is.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Timer clamping jitters each stamp by up to a millisecond, on Windows too; the
    # recordings were made without it, so the guard reads the stamps unclamped.
    prefs = {"privacy.reduceTimerPrecision": False}
    try:
        with Camoufox(executable_path=str(binary), headless=False, os=os_name, firefox_user_prefs=prefs,
                      i_know_what_im_doing=True) as browser:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/")
            for i in range(60):
                page.mouse.move(100 + i * 7, 100 + i * 3)
                page.wait_for_timeout(7 + i % 5)
            page.click("#field")
            page.keyboard.type("timestamps", delay=23)
            for _ in range(6):
                page.mouse.wheel(0, 100)
                page.wait_for_timeout(37)
            page.wait_for_timeout(200)
            seen = page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')")
    finally:
        server.shutdown()
    gaps = []
    for keys in (False, True):
        stamps = sorted(t for type, t in seen if type.startswith("key") == keys)
        gaps += [b - a for a, b in zip(stamps, stamps[1:]) if b > a]
    return gaps


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        windows = probe(resolve_binary(), "windows")
        macos = probe(resolve_binary(), "macos")
    off = [round(g, 3) for g in windows if not on_grid(g)]
    if len(windows) < 50 or off:
        failures.append(f"windows: {len(off)} of {len(windows)} gaps off the 15.625 ms tick: {off[:8]}")
    share = sum(map(on_grid, macos)) / max(1, len(macos))
    if len(macos) < 50 or share > 0.5:
        failures.append(f"macos: {share:.0%} of {len(macos)} gaps on the Windows tick; macOS stamps at high resolution")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: {len(windows)} Windows gaps on the tick, {share:.0%} of macOS gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
