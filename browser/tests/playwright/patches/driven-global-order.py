"""
A page's globals are in the same order whether or not Playwright drives the browser.

A window's WebIDL interfaces are defined on it lazily, the first time anything
needs one, and Object.getOwnPropertyNames(window) lists them in the order they
were defined. Code outside the page that wraps a DOM object for itself still
defines that object's interface on the page's window. Juggler did that before
the page's first script ran: it read `location` (FrameTree), defining
`Location`, and its window actor took DOMWindowCreated and
DOMDocElementInserted as JS events, defining `Event`. A page whose first line
lists its globals saw both early, under Playwright only, on every page.

The guard serves a page whose first script sends that list, loads it in the
binary under test with no driver, then through Playwright with the same launch
options, and fails when the two lists differ.

    python browser/tests/playwright/patches/driven-global-order.py
"""

import difflib
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PAGE_TIMEOUT_S = 60
PAGE = (b"<!doctype html><html><head><script>"
        b"const names = Object.getOwnPropertyNames(window);"
        b"fetch('/names', {method: 'POST', body: JSON.stringify(names)});"
        b"</script></head><body></body></html>")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        self.server.names = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()
        self.server.arrived.set()


def undriven(binary, options, url):
    """The binary with the launcher's prefs, environment and arguments, and no Juggler pipe."""
    profile = tempfile.mkdtemp(prefix="driven-global-order-")
    Path(profile, "user.js").write_text("".join(
        f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in options["firefox_user_prefs"].items()))
    env = {**os.environ, **{k: str(v) for k, v in options["env"].items()}}
    args = [a for a in options["args"] if a not in ("-headless", "--headless")]
    proc = subprocess.Popen([str(binary), *args, "--headless", "--no-remote", "--profile", profile, url],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return profile, proc


def main() -> int:
    from camoufox import launch_options
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    lists = {}
    try:
        server.arrived = threading.Event()
        profile, proc = undriven(binary, launch_options(executable_path=str(binary), headless=True, os="linux"), url)
        try:
            if server.arrived.wait(PAGE_TIMEOUT_S):
                lists["undriven"] = server.names
        finally:
            subprocess.run(["pkill", "-9", "-f", profile], capture_output=True)
            proc.wait()
        server.arrived = threading.Event()
        with Camoufox(executable_path=str(binary), headless=True, os="linux") as browser:
            browser.new_page().goto(url)
            if server.arrived.wait(PAGE_TIMEOUT_S):
                lists["driven"] = server.names
    finally:
        server.shutdown()

    for name in ("undriven", "driven"):
        if name not in lists:
            print(f"FAIL: the {name} page never reported its globals")
            return 1
    a, b = lists["undriven"], lists["driven"]
    print(f"{len(a)} globals undriven, {len(b)} driven")
    if a == b:
        print("PASS: the page's globals are defined in the same order under Playwright")
        return 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            print(f"  {op}: undriven {a[i1:i2]} -> driven {b[j1:j2]}")
    print("FAIL: Playwright changes the order of the page's globals")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
