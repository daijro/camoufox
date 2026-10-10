r"""
The popup blocker is Firefox's, and only the driver has a key.

`dom.disable_open_during_load` is ON in Firefox, so a page that calls
window.open() without a user gesture gets null. Playwright and geckodriver both
ship it off, and that is a one-bit tell any page can read with no permission and
nothing to wait for:

    const w = window.open('', '_blank');
    if (w) { w.close(); /* not a stock browser */ }

Camoufox keeps the blocker on and lifts it for the docShell only while an
explicit juggler Runtime.evaluate / Runtime.callFunction is on the stack
(nsIDocShell.driverPopupsAllowed, patches/popup-blocker-parity.patch), so
page.evaluate(() => window.open(...)) still works. The window is SYNCHRONOUS:
a popup opened after an `await` inside the evaluated function is blocked, as it
would be on stock, or a page polling window.open() on a timer would eventually
land inside somebody else's evaluate.

Both directions are checked here, because either one regressing is silent:
losing the driver's key breaks ~35 upstream tests, and losing the blocker puts
the tell back.

    python browser/tests/playwright/patches/popup-blocker-parity.py
"""

import asyncio
import http.server
import socketserver
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

TIMEOUT_MS = 30_000

PAGE = b"""<!doctype html><meta charset=utf-8><title>popup-parity</title><body>
<script>
// The page's own attempt, at load, with no gesture: stock returns null.
// The answer goes on the DOM, not on `window`: evaluate() runs in an isolated
// world by default, where a main-world global reads back as undefined -- which
// is falsy, so checking one here would pass whatever the browser did.
let opened = null;
try { opened = window.open('', '_pageopen', 'width=120,height=120'); } catch (e) {}
document.body.dataset.pageOpened = String(!!opened);
if (opened) { try { opened.close(); } catch (e) {} }
</script></body>"""


def serve():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


async def probe(binary, port):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, executable_path=str(binary),
                             i_know_what_im_doing=True) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        await page.goto(f"http://127.0.0.1:{port}/")
        opened = await page.evaluate("() => document.body.dataset.pageOpened")
        if opened not in ("true", "false"):
            raise RuntimeError(f"the page never recorded its window.open result: {opened!r}")
        out = {"page_opened": opened == "true"}

        # The driver's own call: this one must work, popup and all.
        try:
            async with context.expect_page(timeout=10_000) as popup_info:
                out["evaluate_opened"] = await page.evaluate(
                    "() => !!window.open('about:blank', '_evalopen')"
                )
            popup = await popup_info.value
            out["popup_seen"] = True
            await popup.close()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            out["evaluate_opened"] = False
            out["popup_seen"] = False
            out["evaluate_error"] = str(exc)[:120]

        # ... and it must not have handed the document an activation.
        out["activation"] = await page.evaluate(
            "() => [navigator.userActivation.hasBeenActive, navigator.userActivation.isActive]"
        )
        out["autoplay"] = await page.evaluate(
            "() => navigator.getAutoplayPolicy('mediaelement')"
        )

        # Past the synchronous window the blocker is back.
        out["async_opened"] = await page.evaluate(
            "async () => { await new Promise(r => setTimeout(r, 40));"
            " return !!window.open('about:blank', '_lateopen'); }"
        )
        return out


def main() -> int:
    binary = resolve_binary()
    srv, port = serve()
    try:
        out = asyncio.run(probe(binary, port))
    finally:
        srv.shutdown()

    failures = []
    if out["page_opened"]:
        failures.append(
            "a page script opened a popup with no user activation "
            "(dom.disable_open_during_load is off, or driverPopupsAllowed is stuck on)"
        )
    if not out["evaluate_opened"] or not out["popup_seen"]:
        failures.append(
            "page.evaluate(() => window.open(...)) did not open a popup "
            f"({out.get('evaluate_error', 'no error reported')})"
        )
    if out["activation"] != [False, False]:
        failures.append(f"the evaluate granted a user activation: {out['activation']}")
    if out["autoplay"] != "allowed-muted":
        failures.append(
            f"autoplay policy is {out['autoplay']!r}, not stock's 'allowed-muted' "
            "without activation"
        )
    if out["async_opened"]:
        failures.append(
            "a popup opened after an await inside an evaluate was allowed -- the "
            "driver's window is meant to be synchronous only"
        )

    print(out)
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: the page is blocked like stock, the driver's evaluate is not, "
          "and no activation was granted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
