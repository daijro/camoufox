"""
Verify a screenshot leaves the page's document.fonts.ready alone.

Playwright reads document.fonts.ready from its utility world before every
screenshot. Gecko creates the ready promise lazily and resolves it with the
FontFaceSet, looking up "then" on it in the page's realm, so a page with a
getter on Object.prototype.then saw it fire when nothing of its own asked.
fontfaceset-privileged-ready.patch hands the driver a promise in its own global.

The driver's promise settles when the fonts finish loading, as the page's
does. It once settled only when a later load began, so a screenshot taken while
a web font was still downloading waited for a load that never came.

What PASS means:
    * a screenshot fires no Object.prototype.then getter in the page;
    * the page's own `await document.fonts.ready` still resolves to the set,
      after the trap has fired for it (the control: the trap works);
    * with a web font still loading, the driver's ready settles, and not
      before the font's load has finished.

    python browser/tests/playwright/patches/fonts-ready-driver.py
"""

import asyncio
import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# Page code, so it runs in the page's own world: page.evaluate() runs in an
# isolated world, which gets the driver's promise and cannot see page expandos.
# Results go back through the DOM, which both worlds see.
TRAP = """
  const hits = [];
  Object.defineProperty(Object.prototype, 'then', {
    configurable: true,
    get() {
      hits.push(Object.prototype.toString.call(this));
      document.body.dataset.hits = JSON.stringify(hits);
      return undefined;
    },
  });
  document.body.dataset.hits = '[]';
"""

OWN_READY = """
  document.fonts.ready.then(set => { document.body.dataset.own = String(set === document.fonts); });
"""


# The font arrives after FONT_DELAY_S and is not a font, so its load ends in
# loadingerror: an end of loading either way, without shipping a font file.
FONT_DELAY_S = 1.0
SLOW_FONT_PAGE = b"""<style>@font-face { font-family: Slow; src: url(/slow.ttf); }
p { font-family: Slow; }</style><p>text</p>
<script>
  document.fonts.addEventListener('loadingerror', () => {
    document.body.dataset.done = String(performance.now());
  });
</script>"""


class SlowFont(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/slow.ttf":
            time.sleep(FONT_DELAY_S)
            body, kind = b"not a font", "font/ttf"
        else:
            body, kind = SLOW_FONT_PAGE, "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def driver_ready_while_loading(browser) -> tuple:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowFont)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        page = await browser.new_page()
        await page.goto(f"http://127.0.0.1:{server.server_address[1]}/", wait_until="commit")
        await page.wait_for_function("document.fonts.status === 'loading'")
        try:
            ready_at = await asyncio.wait_for(
                page.evaluate("document.fonts.ready.then(() => performance.now())"), FONT_DELAY_S + 10)
        except asyncio.TimeoutError:
            return None, None
        done_at = await page.evaluate("document.body.dataset.done")
        return ready_at, float(done_at) if done_at else None
    finally:
        server.shutdown()


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, os="linux", i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.set_content("<p style='font-family: serif'>text</p>")
        await page.add_script_tag(content=TRAP)
        await page.screenshot()
        after_screenshot = await page.evaluate("document.body.dataset.hits")
        await page.add_script_tag(content=OWN_READY)
        await page.wait_for_function("document.body.dataset.own !== undefined")
        own = await page.evaluate("document.body.dataset.own")
        after_own = await page.evaluate("document.body.dataset.hits")
        ready_at, done_at = await driver_ready_while_loading(browser)

    checks = [
        ("a screenshot fires no then getter", after_screenshot == "[]", after_screenshot),
        ("the page's own ready resolves to the set", own == "true", own),
        ("the trap fires for the page's own ready", "[object FontFaceSet]" in after_own, after_own),
        ("the driver's ready settles while a web font loads", ready_at is not None, ready_at),
        ("and not before the font's load has finished",
         ready_at is not None and done_at is not None and ready_at >= done_at, (ready_at, done_at)),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
