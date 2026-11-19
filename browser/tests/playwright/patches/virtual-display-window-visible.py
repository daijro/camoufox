r"""
On the launcher's virtual display the browser window is on screen, so pages behave as on a desktop.

headless='virtual' (and, on Linux, headless=True) runs the browser on a private
Xvfb whose root window is 1x1 by default (virtdisplay.DEFAULT_SCREEN). An identity
places its window where a desktop would (window.screenX/Y, e.g. 319,76). A window
that does not cover the root's one pixel is entirely off screen: X reports it
fully obscured, and Firefox then never resolves
`navigator.mediaDevices.enumerateDevices()` -- the promise hangs, which a page
sees as a timeout no desktop Firefox shows. On a 1x1 root a window at 0,0
resolves, while one at 319,76 does not; both resolve on a desktop-sized root.

Cause (MOZ_LOG=Widget:5): off the root, X sends VisibilityNotify
FULLY_OBSCURED, nsWindow::OnVisibilityNotifyEvent marks the toplevel occluded,
and MediaDevices::MaybeResumeDeviceExposure holds device exposure for an
inactive browsing context. Nothing else a page reads changed (visibilityState,
focus/blur, hasFocus, rAF cadence, IntersectionObserver, timers, :focus-visible
all equal on and off the root -- Camoufox's own focus handling hides the
second gate from them). The root stays 1x1 (tribal rule
virtual-display-default-1x1x24, throughput); virtual-display-off-root-not-occluded.patch
stops a window outside the root counting as occluded. The patch also focuses a
new top-level window when no window manager runs, at its first VisibilityNotify.
Without that, X focus follows the pointer, which a 1x1 root pins at 0,0, so a
window elsewhere never becomes active. Focusing earlier from nsWindow::OnMap
fails because the top-level X window is not mapped yet.

The check: the build under test, on the launcher's own VirtualDisplay (its
default size), with a window at 319,76 1280x900, must resolve enumerateDevices
within 5 s.

    python browser/tests/playwright/patches/virtual-display-window-visible.py
"""

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "python" / "src"))

PAGE = b"""<!doctype html><meta charset=utf-8><body><script>
setTimeout(() => {
  Promise.race([
    navigator.mediaDevices.enumerateDevices().then(d => d.map(x => x.kind).join(',') || 'empty'),
    new Promise(r => setTimeout(() => r('TIMEOUT'), 5000)),
  ]).then(e => fetch('/r', {method: 'POST', body: JSON.stringify(
    {enumerate: e, screen: [screenX, screenY, outerWidth, outerHeight]})}));
}, 1500);
</script></body>"""


def main() -> int:
    from camoufox.virtdisplay import VirtualDisplay

    got, done = {}, threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)

        def do_POST(self):
            got.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="vd-visible-")
    vd = VirtualDisplay()
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET")}
        env["DISPLAY"] = vd.get()
        env["CAMOU_CONFIG_1"] = json.dumps({"window.screenX": 319, "window.screenY": 76,
                                            "window.outerWidth": 1280, "window.outerHeight": 900})
        proc = subprocess.Popen([str(resolve_binary()), "-no-remote", "-profile", profile,
                                 f"http://127.0.0.1:{srv.server_address[1]}/"],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            done.wait(60)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        vd.kill()
        srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    print(json.dumps({"display": vd.screen, **got}))
    if got.get("enumerate") in (None, "TIMEOUT"):
        print(f"FAIL: enumerateDevices() did not resolve with the window at 319,76 on the {vd.screen} "
              f"virtual display ({got or 'no report'})")
        return 1
    print("PASS: the window is on the virtual display and enumerateDevices() resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
