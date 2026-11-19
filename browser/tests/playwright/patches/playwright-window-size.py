"""
A Playwright launch gives its pages the identity's window, as a plain launch does.

CamoufoxWindow.sys.mjs sizes the first window so that its content area is the
identity's innerWidth x innerHeight. Playwright starts the browser on
about:blank, where Firefox shows the bookmarks toolbar that appears only on a
new tab page (31 px on Linux), and the window was sized with that toolbar
counted as chrome. At the first real page the toolbar went away and the page
read 31 px more innerHeight and outerHeight than the identity claims. The
new-tab-only toolbar is now left out of the sizing.

Runs headless and, where Xvfb is installed, on a private Xvfb display.

    python browser/tests/playwright/patches/playwright-window-size.py
"""

import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

GEOMETRY = {"screen.width": 1920, "screen.height": 1080, "screen.availWidth": 1920, "screen.availHeight": 1080,
            "screen.availLeft": 0, "screen.availTop": 0, "window.outerWidth": 1282, "window.outerHeight": 927,
            "window.innerWidth": 1280, "window.innerHeight": 815, "window.screenX": 319, "window.screenY": 76}
READ = "() => [outerWidth, outerHeight, innerWidth, innerHeight]"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<!doctype html><title>w</title><p>w</p>")


def xvfb():
    """A private Xvfb display, or None where there is none to start."""
    if not shutil.which("Xvfb"):
        return None, None
    r, w = os.pipe()
    proc = subprocess.Popen(["Xvfb", "-displayfd", str(w), "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                            pass_fds=(w,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(w)
    num = b""
    deadline = time.monotonic() + 10
    while not num.endswith(b"\n") and time.monotonic() < deadline:
        chunk = os.read(r, 16)
        if not chunk:
            break
        num += chunk
    os.close(r)
    if not num.strip().isdigit():
        proc.kill()
        return None, None
    return proc, ":" + num.decode().strip()


def probe(binary, display):
    from camoufox.sync_api import Camoufox

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    # The launcher checks the window against the monitor of its own DISPLAY,
    # so the process takes this display rather than handing it to the browser.
    outer = {k: os.environ.pop(k, None) for k in ("DISPLAY", "WAYLAND_DISPLAY")}
    if display:
        os.environ["DISPLAY"] = display
    try:
        for persistent in (False, True):
            prof = tempfile.mkdtemp(prefix="cf-window-size-")
            kw = dict(executable_path=str(binary), headless=display is None, os="linux", config=GEOMETRY,
                      i_know_what_im_doing=True)
            if persistent:
                kw.update(persistent_context=True, user_data_dir=prof)
            try:
                with Camoufox(**kw) as b:
                    page = (b.pages[0] if persistent and b.pages else b.new_page())
                    page.goto(f"http://127.0.0.1:{srv.server_port}/", wait_until="load")
                    page.wait_for_timeout(1500)
                    out["persistent" if persistent else "browser"] = page.evaluate(READ)
            finally:
                shutil.rmtree(prof, ignore_errors=True)
    finally:
        srv.shutdown()
        os.environ.pop("DISPLAY", None)
        os.environ.update({k: v for k, v in outer.items() if v is not None})
    return out


def main() -> int:
    binary = resolve_binary()
    want = [GEOMETRY["window.innerWidth"], GEOMETRY["window.innerHeight"]]
    failures, seen = [], {}
    proc, display = xvfb()
    try:
        for where in ("headless", display):
            if where is None:
                continue
            for mode, got in probe(binary, None if where == "headless" else where).items():
                seen[f"{where} {mode}"] = got
                if got[2:] != want:
                    failures.append(f"{where} {mode}: inner {got[2]}x{got[3]} (outer {got[0]}x{got[1]}), "
                                    f"want the identity's {want[0]}x{want[1]}")
    finally:
        if proc:
            proc.kill()
            proc.wait()
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(f"PASS: Playwright pages get the identity's viewport: {seen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
