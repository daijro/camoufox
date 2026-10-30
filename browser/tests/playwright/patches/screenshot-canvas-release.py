r"""
A screenshot frees its canvas once it is encoded (#959).

Page.screenshot draws the page into a canvas in the chrome document and encodes
it. The canvas then held its pixels until a garbage collection, and on Windows
that memory stayed committed until the browser closed: 80 JPEG screenshots in
one browser retained about 916 MiB. The handler now sizes the canvas to zero on
every path out.

The guard takes screenshots in one browser and reads the parent process's heap
through Marionette before and after, with no GC in between. A canvas that
waits for a GC leaves most of its 7.9 MiB pixel buffer per screenshot (3.7 to
6 MiB measured); a freed one leaves only the encoded image strings (0.3 to
1 MiB).

    python browser/tests/playwright/patches/screenshot-canvas-release.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, launch_kwargs, marionette_args  # noqa: E402

SHOTS = 20
WIDTH, HEIGHT = 1920, 1080
HEAP = 'return Cc["@mozilla.org/memory-reporter-manager;1"].getService(Ci.nsIMemoryReporterManager).heapAllocated;'


def main() -> int:
    from camoufox.sync_api import Camoufox

    port = free_port()
    with Camoufox(**launch_kwargs(args=marionette_args(), firefox_user_prefs={"marionette.port": port},
                                  i_know_what_im_doing=True)) as browser:
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.set_content('<body style="margin:0;background:#234">x</body>')
        page.screenshot()
        m = Marionette(port)
        try:
            m.js("Cu.forceGC(); Cu.forceCC(); return 0;")
            before = m.js(HEAP)
            for i in range(SHOTS):
                page.screenshot(type="jpeg" if i % 2 else "png")
            grown = m.js(HEAP) - before
        finally:
            m.close()

    canvas = WIDTH * HEIGHT * 4
    print(f"  parent heap grew {grown / SHOTS / 2**20:.2f} MiB per screenshot "
          f"(a canvas is {canvas / 2**20:.1f} MiB)")
    if grown / SHOTS >= canvas / 4:
        print("FAIL: screenshot canvases stay allocated after they are encoded")
        return 1
    print("PASS: screenshot canvases are freed once encoded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
