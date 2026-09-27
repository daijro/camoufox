"""
Verify the `addons` config is installed once per launch (browser-init.patch).

browser-init.patch installs the `addons` entries (uBlock Origin by default) as
temporary addons from gBrowserInit, which runs for every browser window, and
Juggler opens a window for every page of every new context. Installing an
already-installed temporary addon restarts it. A navigation that uBO's
webRequest listener had suspended when the restart hit is never resumed, so
page.goto times out (daijro/camoufox#185).

    contexts   create CONTEXTS contexts, one page each, and navigate it
    once       uBO's background page loaded exactly once (MOZ_LOG
               DocumentChannel records every document load in the parent)
    no hang    every navigation completed

    python tests/patches/addons-install-once.py
"""

import functools
import http.server
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

CONTEXTS = 12
# A request dropped by a restart never finishes. A healthy local load finishes
# well inside this even when uBO holds it while compiling its filter lists.
GOTO_TIMEOUT_MS = 60000
BACKGROUND_LOAD = re.compile(r"DocumentChannelParent Init \[this=\w+, uri=moz-extension://[^/]+/background")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    # A page torn down mid-response breaks the pipe; the default handler's
    # traceback would replace the verdict as the tail of the guard's output.
    def handle_error(self, request, client_address):
        pass


def background_loads(log_dir: Path) -> int:
    # MOZ_LOG_FILE gets a suffix per process; count every file rather than
    # guess which one is the parent's.
    return sum(len(BACKGROUND_LOAD.findall(p.read_text(errors="replace")))
               for p in log_dir.glob("log*"))


def main() -> int:
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    site = tempfile.mkdtemp()
    Path(site, "p.html").write_text("<!doctype html><meta charset=utf-8><body>x</body>")
    srv = QuietServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/p.html"

    log_dir = Path(tempfile.mkdtemp())
    env = {**os.environ, "MOZ_LOG": "DocumentChannel:5", "MOZ_LOG_FILE": str(log_dir / "log")}
    created = 0
    hang = None
    try:
        with Camoufox(headless=True, executable_path=str(binary), env=env,
                      i_know_what_im_doing=True) as browser:
            for _ in range(CONTEXTS):
                ctx = browser.new_context()
                page = ctx.new_page()
                try:
                    page.goto(url, timeout=GOTO_TIMEOUT_MS)
                except Exception as exc:
                    hang = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
                    break
                ctx.close()
                created += 1
    finally:
        srv.shutdown()
        shutil.rmtree(site, ignore_errors=True)
    loads = background_loads(log_dir)
    shutil.rmtree(log_dir, ignore_errors=True)

    print(f"contexts: {created}/{CONTEXTS} navigated, uBO background page loads: {loads}"
          + (f", hang: {hang}" if hang else ""))
    print()
    failures = []
    if loads == 0:
        failures.append("uBO's background page never loaded -- the addon did not start, check is vacuous")
    elif loads > 1:
        opened = created + (1 if hang else 0)
        failures.append(f"uBO restarted: its background page loaded {loads} times across {opened} contexts")
    if hang:
        failures.append(f"navigation {created + 1} never completed ({hang})")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: addons installed once per launch; every navigation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
