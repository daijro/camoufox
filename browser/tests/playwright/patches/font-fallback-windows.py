"""
A Windows identity picks the fonts stock Firefox picks on Windows, per script.

The page draws a sample of 28 scripts (Hangul, Thai, Devanagari, Arabic,
Georgian, emoji, ...) in serif, sans-serif and monospace, on a canvas and in
lang-tagged spans, and records the widths. assets/font-fallback-windows.json is
the same page in stock Firefox 152.0.4 on Windows 10 (devicePixelRatio 1).
156.0.1 ships the same Windows font prefs (all.js) and per-script table
(gfxWindowsPlatform.cpp), so it is the reference until re-measured on 156.

This build is a Linux build, so without the fixes it resolved fonts the Linux
way: 75 of 168 widths matched Windows (emoji 192 vs 263.6, Thai 323 vs 361.6,
Mongolian 115.8 vs 74.1). The fixes are Windows' font.name-list defaults from
the launcher, async fallback off on a Linux host, slight hinting in the bundled
Windows fonts.conf, and fallback-fonts-claimed-os.patch for the per-script
table.

The scale is pinned to 1: at devicePixelRatio 1.25 every canvas width moves by
~0.26% (FreeType's fixed-point advances at another pixel size), as Windows'
would at 125% too -- a different reference, not a mismatch.

    python browser/tests/playwright/patches/font-fallback-windows.py
"""

import functools
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
TOLERANCE_PX = 0.5
# Matching widths out of 168; raise it as parity improves, never lower it.
MIN_MATCHING = 160


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def log_error(self, *a):
        pass

    def do_POST(self):
        self.send_response(204)
        self.end_headers()


def main() -> int:
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    reference = json.loads((ASSETS / "font-fallback-windows.json").read_text(encoding="utf-8"))
    site = tempfile.mkdtemp()
    shutil.copy(ASSETS / "font-fallback.html", Path(site) / "fb.html")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/fb.html"
    try:
        with Camoufox(os="windows", headless=True, executable_path=str(binary),
                      firefox_user_prefs={"layout.css.devPixelsPerPx": "1"},
                      i_know_what_im_doing=True) as browser:
            page = browser.new_page()
            page.goto(url)
            page.wait_for_function("document.body.dataset.r", timeout=60000)
            got = json.loads(page.evaluate("document.body.dataset.r"))
    finally:
        srv.shutdown()

    if got.get("dpr") != 1:
        print(f"FAIL: devicePixelRatio {got.get('dpr')} -- the scale pin did not hold, check is vacuous")
        return 1

    total = 0
    mismatches = []
    for where in ("canvas", "dom"):
        for script, generics in reference[where].items():
            for generic, want in generics.items():
                total += 1
                have = got[where][script][generic]
                if abs(have - want) > TOLERANCE_PX:
                    mismatches.append(f"{where}/{script}/{generic}: {have:.2f} vs Windows {want:.2f}")
    matching = total - len(mismatches)
    print(f"{matching}/{total} per-script widths match stock Firefox on Windows")
    for m in mismatches:
        print("   ", m)
    print()
    if matching < MIN_MATCHING:
        print(f"FAIL: {matching} match, fewer than the {MIN_MATCHING} this build reached")
        return 1
    print(f"PASS: at least {MIN_MATCHING} of {total} match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
