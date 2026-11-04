"""
Verify uBlock Origin blocks with the filter lists packaged in the release the
build bundles, and never downloads them at launch (scripts/fetch-ubo.py
freeze_lists makes the bundled uBO's autoUpdate default false; a policy would
put Firefox in enterprise mode).

uBO's own default updates every list from its CDNs shortly after launch: two
seconds after it is ready when a packaged list is past twice its expiry, 37
seconds otherwise. Every launch is a fresh profile, so that was about 2.7 MB
through the user's proxy per launch, and blocking that depended on the day.

The browser runs through a local proxy that records each CONNECT and refuses
it, so the guard needs no network. Camoufox installs uBO after the first window
has loaded, so the guard reloads a local page with an ad script until uBO
blocks it. The proxy records a CONNECT before refusing it, and the page's load
event waits for the refused script, so each load's verdict is settled when it
returns.

    active   uBO blocks the ad script within READY_S of launch
    control  the page's ordinary image host is requested (the proxy sees traffic)
    frozen   no host uBO fetches lists from (its assets.json) is contacted
             from launch until WAIT_S after uBO first blocks

    python browser/tests/playwright/patches/ubo-lists-frozen.py
"""

import functools
import http.server
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# Past uBO's 37-second scheduled update, with room for its 5-second spacing
# between list fetches.
WAIT_S = 50
READY_S = 60
AD_HOST = "pagead2.googlesyndication.com"
CONTROL_HOST = "example.com"
AD_PAGE = (f'<!doctype html><script src="https://{AD_HOST}/pagead/js/adsbygoogle.js"></script>'
           f'<img src="https://{CONTROL_HOST}/">')


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def list_hosts(addon_path: str) -> set:
    """Every host uBO's packaged asset registry names as a source."""
    assets = json.loads(Path(addon_path, "assets", "assets.json").read_text())
    urls = []
    for entry in assets.values():
        for key in ("contentURL", "cdnURLs", "patchURLs"):
            value = entry.get(key) or []
            urls.extend([value] if isinstance(value, str) else value)
    return {urlparse(u).hostname for u in urls if u.startswith("http")}


def blocks_ad(page, url: str, hosts: list) -> bool:
    before = hosts.count(AD_HOST)
    page.goto(url)
    return hosts.count(AD_HOST) == before


def recording_proxy(hosts: list) -> socket.socket:
    def handle(conn):
        with conn:
            head = conn.recv(4096).decode(errors="replace")
            method, _, rest = head.partition(" ")
            if method == "CONNECT":
                hosts.append(rest.split(" ", 1)[0].rsplit(":", 1)[0])
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")

    def serve():
        while True:
            conn, _ = sock.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    threading.Thread(target=serve, daemon=True).start()
    return sock


def main() -> int:
    from camoufox.addons import DefaultAddons, get_addon_path
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    ubo = get_addon_path(DefaultAddons.UBO.name, binary)
    if not Path(ubo, "manifest.json").is_file():
        print(f"FAIL: the build bundles no uBlock Origin at {ubo} -- check is vacuous")
        return 1
    ubo_hosts = list_hosts(ubo)

    site = tempfile.mkdtemp()
    Path(site, "ad.html").write_text(AD_PAGE)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    hosts: list = []
    proxy = recording_proxy(hosts)
    try:
        with Camoufox(headless=True, executable_path=str(binary), i_know_what_im_doing=True,
                      proxy={"server": f"http://127.0.0.1:{proxy.getsockname()[1]}"}) as browser:
            page = browser.new_page()
            deadline = time.monotonic() + READY_S
            while not blocks_ad(page, f"{base}/ad.html", hosts):
                if time.monotonic() > deadline:
                    print(f"FAIL: uBO did not block {AD_HOST} within {READY_S}s -- check is vacuous")
                    return 1
                time.sleep(1)
            time.sleep(WAIT_S)
    finally:
        proxy.close()
        srv.shutdown()
        shutil.rmtree(site, ignore_errors=True)

    contacted = sorted(set(hosts))
    fetched = sorted(set(contacted) & ubo_hosts)
    print(f"hosts contacted until {WAIT_S}s after uBO first blocked: {', '.join(contacted) or 'none'}")
    print()
    failures = []
    if CONTROL_HOST not in contacted:
        failures.append(f"{CONTROL_HOST} was never requested -- the proxy saw no traffic, check is vacuous")
    if fetched:
        failures.append(f"uBO downloaded filter lists from {', '.join(fetched)}")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: uBO blocks with its packaged lists and downloads none at launch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
