"""
Verify Firefox gives each browser context its own web-content process.

Per-context values cached in a content process (fontconfig's family-name
memos, #941/#942, and any other process-wide cache keyed without a context)
leak across identities only when two contexts share one content process.
Firefox 158's SharedWeb pool keys the process by container and private mode,
which is why #942 was not needed on 158.

This guard asserts the property that makes the failure impossible: with the
default process pool, three contexts keep three web-content processes alive.
If a future Firefox merges the pools again, this fails before a font,
localStorage or identity leak can hide behind shared renderer state.

    python browser/tests/playwright/patches/context-process-isolation.py
"""

import functools
import http.server
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

CONTEXTS = 3
WAIT_S = 60
WEB_CONTENT = {"Web Content", "Isolated Web Co"}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def web_content_processes(binary: Path) -> list[tuple[int, str]]:
    """Every live web-content process from this exact browser binary."""
    found = []
    real = os.path.realpath(binary)
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            if os.path.realpath(f"/proc/{entry}/exe") != real:
                continue
            name = Path(f"/proc/{entry}/comm").read_text().strip()
        except OSError:
            continue
        if name in WEB_CONTENT:
            found.append((int(entry), name))
    return sorted(found)


def main() -> int:
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    site = tempfile.mkdtemp()
    Path(site, "index.html").write_text("<!doctype html><meta charset=utf-8><body>isolation</body>")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=site)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"

    try:
        with Camoufox(
            headless=True,
            executable_path=str(binary),
            i_know_what_im_doing=True,
        ) as browser:
            contexts = []
            for _ in range(CONTEXTS):
                context = browser.new_context()
                page = context.new_page()
                page.goto(url)
                contexts.append(context)

            deadline = time.monotonic() + WAIT_S
            processes = web_content_processes(binary)
            while len(processes) < CONTEXTS and time.monotonic() < deadline:
                time.sleep(0.25)
                processes = web_content_processes(binary)
    finally:
        server.shutdown()

    print(f"{CONTEXTS} contexts -> {processes}")
    if len(processes) < CONTEXTS:
        print(
            f"FAIL: {CONTEXTS} contexts share {len(processes)} web-content process(es); "
            "per-context state can leak through renderer caches"
        )
        return 1
    print("PASS: contexts use separate web-content processes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
