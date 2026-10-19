"""
Verify the `mw:` main-world escape hatch for init scripts (daijro/camoufox#738).

add_init_script() lands in the default world, which since the isolated-world
change (#707) is a sandbox the page cannot see. A script installed that way to
patch what a *site* observes -- canvas noise, API shims, anything -- stopped
reaching page script entirely, and did so silently:

  * page.evaluate() reads the value back happily, because that is the same world
    the init script landed in, so the obvious probe reports success;
  * "mw:" was accepted without complaint. Playwright's InitScript constructor
    wraps every body in `(() => { ... })();`, so the prefix ends up inside the
    wrapper where it parses as a label statement -- valid, and does nothing;
  * init scripts reach ExecutionContext.evaluateScriptSafely(), whose catch
    writes to dump() and returns, so even a throwing script surfaces nothing.

For a tool whose job is spoofing, silently not spoofing is the worst failure
available, which is why the refusals on this path are loud.

This measures what the PAGE sees -- an inline <script> writes window.__marker
into document.title -- not what automation sees. Reading it back through
page.evaluate() is exactly the probe that cannot see the bug.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python browser/tests/playwright/patches/main-world-init-script.py
Against an unpackaged objdir build, run `make -C browser stage-fonts` first.

What PASS means:
    * with main_world_eval=False, an "mw:" init script does NOT reach the page
      (it fails closed rather than landing somewhere unexpected);
    * with main_world_eval=True, an "mw:" init script DOES reach the page, so a
      site observes it;
    * an unprefixed init script stays isolated either way -- the page never sees
      it, and that is the shipped default;
    * the main-world case holds across repeated launches. The original report
      measured 2 failures in 8 launches from the main-world global being
      captured before the document settled on one, so a single green run is not
      evidence.
"""

import asyncio
import http.server
import socketserver
import sys
import threading
from typing import Any, Dict, Tuple

from camoufox.async_api import AsyncCamoufox
from helpers import launch_kwargs

# The page reports, in its own world, whether the init script reached it.
PROBE_PAGE = (
    "<!doctype html><meta charset='utf-8'><body><script>"
    "document.title = 'marker=' + (window.__marker || 'absent');"
    "</script></body>"
)

PLAIN_SCRIPT = "window.__marker = 'present';"
MAIN_WORLD_SCRIPT = "mw:window.__marker = 'present';"

MAIN_WORLD_LAUNCHES = 8


class _Probe(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = PROBE_PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass


def _serve() -> Tuple[socketserver.TCPServer, str]:
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", 0), _Probe)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


async def _page_sees(url: str, script: str, main_world_eval: bool) -> bool:
    """Whether the page's own script observed the init script's write."""
    async with AsyncCamoufox(**launch_kwargs(os="linux", main_world_eval=main_world_eval)) as browser:
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        await context.add_init_script(script)
        page = await context.new_page()
        await page.goto(url, wait_until="load")
        return (await page.title()) == "marker=present"


def _check(results: Dict[str, bool], label: str, got: Any, expected: Any) -> None:
    ok = got == expected
    results[label] = ok
    suffix = "" if ok else f" (expected {expected!r})"
    print(f"  {'PASS' if ok else 'FAIL'} {label:46} -> {got!r}{suffix}")


async def main() -> int:
    server, url = _serve()
    results: Dict[str, bool] = {}
    try:
        print("\n=== main_world_eval=False (shipped default) ===")
        _check(
            results,
            "plain init script stays out of the page",
            await _page_sees(url, PLAIN_SCRIPT, main_world_eval=False),
            False,
        )
        _check(
            results,
            '"mw:" without the flag fails closed',
            await _page_sees(url, MAIN_WORLD_SCRIPT, main_world_eval=False),
            False,
        )

        print("\n=== main_world_eval=True ===")
        _check(
            results,
            "plain init script still stays out of the page",
            await _page_sees(url, PLAIN_SCRIPT, main_world_eval=True),
            False,
        )

        print(f"\n=== main_world_eval=True, {MAIN_WORLD_LAUNCHES} launches ===")
        reached = 0
        for attempt in range(1, MAIN_WORLD_LAUNCHES + 1):
            if await _page_sees(url, MAIN_WORLD_SCRIPT, main_world_eval=True):
                reached += 1
            else:
                print(f"       launch {attempt}: page did NOT see the init script")
        _check(
            results,
            '"mw:" reaches the page on every launch',
            reached,
            MAIN_WORLD_LAUNCHES,
        )
    finally:
        server.shutdown()
        server.server_close()

    passed = all(results.values())
    print()
    print(
        "PASS: main-world init scripts behave"
        if passed
        else "FAIL: main-world init scripts are broken"
    )
    print()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
