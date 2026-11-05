r"""
Every frame and popup reports its own mozInnerScreenX/Y; the identity's
content position is where the first window's content area starts.

mozInnerScreenX/Y is where a window's content area starts on screen. Stock
derives it per window: an iframe's is its parent's plus the iframe's content
offset in the page (its box plus its border), and a popup's is its own
window's. The Pro overlay's window-moz-inner-screen.patch answered the
configured window.mozInnerScreenX/Y from MaskConfig for EVERY window, so an
iframe 137px into the page and a popup opened at left=60,top=70 read the main
window's 206.4,132.8 -- the same class as LEAKS rows 116 (innerWidth/Height)
and 124 (screenX/Y). It also left the top window's own screenX where it was,
so mozInnerScreenX - screenX disagreed with the window's frame.

Now nothing reads the value in content: CamoufoxWindow.sys.mjs places the
first window so its content area starts at the configured position (to the
nearest device pixel the window manager can place it at), and every window
reports where it really is, as in stock.

    python browser/tests/playwright/patches/frame-inner-screen-position.py
"""

import asyncio
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

CLAIMED = [206.4, 132.8]
POPUP = [60, 70]
SAME = [137, 91]           # same-origin iframe, no border
CROSS = [211, 303, 5]      # cross-origin iframe and its border width

TOP = f"""<!doctype html><body style="margin:0">
<iframe id=so src="/inner" style="position:absolute;left:{SAME[0]}px;top:{SAME[1]}px;
 width:300px;height:150px;border:0"></iframe>
<iframe id=xo style="position:absolute;left:{CROSS[0]}px;top:{CROSS[1]}px;
 width:300px;height:150px;border:{CROSS[2]}px solid red"></iframe>
<script>document.getElementById('xo').src = 'http://127.0.0.2:' + location.port + '/inner';</script>
"""
INNER = "<!doctype html><body style='margin:0'>inner"
READ = "() => [mozInnerScreenX, mozInnerScreenY, screenX, screenY]"


class Pages(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (TOP if self.path.startswith("/top") else INNER).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def probe(binary, port):
    from camoufox.async_api import AsyncCamoufox

    config = {"window.mozInnerScreenX": CLAIMED[0], "window.mozInnerScreenY": CLAIMED[1],
              "screen.width": 1920, "screen.height": 1080,
              "screen.availWidth": 1920, "screen.availHeight": 1080,
              "screen.availLeft": 0, "screen.availTop": 0,
              "window.outerWidth": 1200, "window.outerHeight": 800}
    async with AsyncCamoufox(headless=True, executable_path=str(binary), config=config,
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto(f"http://127.0.0.1:{port}/top")
        await page.wait_for_load_state("load")
        await asyncio.sleep(1.5)  # past CamoufoxWindow's startup placement
        top = await page.evaluate(READ)
        frames = {}
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            key = "so" if frame.url.startswith("http://127.0.0.1") else "xo"
            frames[key] = await frame.evaluate(READ)
        async with page.context.expect_page() as popup_info:
            await page.evaluate(
                f"() => {{ window.open('about:blank', '', "
                f"'width=400,height=300,left={POPUP[0]},top={POPUP[1]}'); }}")
        popup = await popup_info.value
        await popup.wait_for_load_state()
        await asyncio.sleep(1.0)
        pop = await popup.evaluate(READ)
        return top, frames, pop


def main() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        top, frames, pop = asyncio.run(probe(resolve_binary(), server.server_address[1]))
    finally:
        server.shutdown()
    print(f"top mozInnerScreen {top[:2]} screen {top[2:]}")
    print(f"same-origin iframe at {SAME}: {frames.get('so')}")
    print(f"cross-origin iframe at {CROSS[:2]} border {CROSS[2]}: {frames.get('xo')}")
    print(f"popup at {POPUP}: mozInnerScreen {pop[:2]} screen {pop[2:]}")
    failures = []
    if any(abs(top[i] - CLAIMED[i]) > 1 for i in range(2)):
        failures.append(f"the top window's content area is not at the identity's {CLAIMED}")
    # The content area sits inside the window: past the left resize border
    # (0 to 8 px on Windows, 0 headless) and below the toolbars.
    if not (0 <= top[0] - top[2] <= 16 and 0 <= top[1] - top[3] <= 200):
        failures.append(f"the top window's content area {top[:2]} is not inside its window at "
                        f"{top[2:]}")
    for key, offset in (("so", SAME), ("xo", [CROSS[0] + CROSS[2], CROSS[1] + CROSS[2]])):
        got = frames.get(key)
        if got is None:
            failures.append(f"iframe {key} was not found")
            continue
        delta = [round(got[i] - top[i], 2) for i in range(2)]
        if delta != offset:
            failures.append(f"iframe {key} reports mozInnerScreen {got[:2]}: {delta} from the "
                            f"top window's, where stock adds its content offset {offset}")
    if pop[2:] != POPUP:
        failures.append(f"the popup is not at the {POPUP} its features asked for")
    if pop[0] < pop[2] or pop[1] < pop[3] or pop[:2] == top[:2]:
        failures.append(f"the popup reports mozInnerScreen {pop[:2]}, not inside its own "
                        f"window at {pop[2:]}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: every frame and popup derives its own mozInnerScreenX/Y, as in stock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
