r"""
Verify a long press on a link opens no Link Preview panel (#961).

Firefox opens its AI Link Preview card after a primary-button press held on a
link for browser.ml.linkPreview.longPressMs (1000 ms). Automation that holds the
mouse down on a link -- a press-and-hold check, a slow drag -- opened the card
over the page, where it stayed after the release, and when the preview fetch
failed it read "Camoufox can't preview this link". The card is browser UI that
no page can read, so camoufox.cfg turns the feature off.

The guard launches camoufox through Playwright, headed on a private Xvfb display,
with Marionette also enabled so the chrome document can be inspected. It holds
the mouse on a link for twice the long-press delay and asserts no
#link-preview-panel exists. A second launch with the feature turned back on
asserts the same press opens the panel, so the check is not vacuous.

    python browser/tests/playwright/patches/long-press-no-link-preview.py
"""

import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, resolve_binary  # noqa: E402

PAGE = b'<!DOCTYPE html><html><body><a id="a" href="/article" style="font-size:40px">A link</a></body></html>'
PANEL = 'return document.getElementById("link-preview-panel")?.state ?? null;'


def serve():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def panel_after_long_press(binary: Path, url: str, prefs: dict):
    from camoufox.sync_api import Camoufox

    port = free_port()
    with Camoufox(headless=False, executable_path=str(binary), args=marionette_args(),
                  firefox_user_prefs={"marionette.port": port, **prefs}, i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.goto(url)
        box = page.locator("#a").bounding_box()
        page.mouse.move(box["x"] + 10, box["y"] + box["height"] / 2)
        page.mouse.down()
        time.sleep(2)
        m = Marionette(port)
        try:
            return m.js(PANEL)
        finally:
            m.close()
            page.mouse.up()


def main() -> int:
    binary = resolve_binary()
    server = serve()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        with hidden_display():
            default = panel_after_long_press(binary, url, {})
            enabled = panel_after_long_press(binary, url, {"browser.ml.linkPreview.enabled": True})
    finally:
        server.shutdown()

    print(f"  default: #link-preview-panel {default}; feature turned on: {enabled}")
    failures = []
    if enabled != "open":
        failures.append("with the feature on the press opened no panel -- the check is vacuous")
    if default is not None:
        failures.append(f"a long press on a link opened the Link Preview panel ({default})")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a long press on a link opens no Link Preview panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
