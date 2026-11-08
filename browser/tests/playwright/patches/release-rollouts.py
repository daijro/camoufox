r"""
Firefox's 100% release rollouts are on, as in stock Firefox.

Stock Firefox on the release channel gets its rollouts from Nimbus; Camoufox's
update channel is "default", which no rollout targets, so it ran without them.
compression-dictionaries-rollout-153-release turns on HTTP
compression dictionaries for every release profile: a server that sends
Use-As-Dictionary gets Available-Dictionary and dcb/dcz back from stock, and a
page reads <link>.relList.supports("compression-dictionary") as true (false
without it; HTMLLinkElement.cpp keys the supported rel set on
network.http.dictionaries.enable). camoufox.cfg now sets the rollouts' prefs as
defaults.

The guard also has a dictionary used, over HTTPS: the request for a resource a
stored dictionary matches must carry Available-Dictionary and end its
Accept-Encoding in "dcb, dcz", as stock's does. A launch that sets
headers.Accept-Encoding (a caller's own header, or one copied from stock's)
used to lose them: the override replaced the dictionary list
(nsHttpHandler::SetAcceptEncodings, network-patches.patch), which stock builds
as the secure list plus network.http.accept-encoding.dictionary
(dictionaryEncodings [] beside stock's ["dcb", "dcz"]).

    python browser/tests/playwright/patches/release-rollouts.py
"""

import http.server
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402


SOURCE = b"release-rollouts compression dictionary " + b"0123456789abcdef" * 256


def dictionary_server(tmp: Path):
    """An HTTPS server whose /dict/source.txt offers itself as a dictionary for
    /dict/target*; returns (url, the headers of each /dict/target request)."""
    key, cert = tmp / "key.pem", tmp / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
    targets = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            extra = {}
            if path == "/dict/source.txt":
                body, extra = SOURCE, {"Use-As-Dictionary": 'match="/dict/target*"', "Cache-Control": "max-age=3600"}
            elif path.startswith("/dict/target"):
                targets.append({"available-dictionary": self.headers.get("Available-Dictionary"),
                                "accept-encoding": self.headers.get("Accept-Encoding")})
                body, extra = b"target", {"Cache-Control": "no-store"}
            else:
                body = b"<!doctype html><p>x"
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if path == "/" else "text/plain")
            for name, value in extra.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(str(cert), str(key))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"https://localhost:{server.server_address[1]}/", targets


def use_dictionary(config: dict, tmp: Path):
    """relList support, and the headers of the request a stored dictionary matches."""
    from camoufox.sync_api import Camoufox

    url, targets = dictionary_server(tmp)
    with Camoufox(**launch_kwargs(os="linux", config=config, i_know_what_im_doing=True)) as browser:
        page = browser.new_page(ignore_https_errors=True)
        page.goto(url)
        supports = page.evaluate(
            "document.createElement('link').relList.supports('compression-dictionary')")
        page.evaluate("fetch('/dict/source.txt').then(r => r.text())")
        time.sleep(1.5)
        page.evaluate("fetch('/dict/target.txt').then(r => r.text())")
    return supports, targets


def main() -> int:
    failures = []
    for name, config in (("default", {}), ("headers.Accept-Encoding set",
                                           {"headers.Accept-Encoding": "gzip, deflate, br, zstd"})):
        with tempfile.TemporaryDirectory() as tmp:
            supports, targets = use_dictionary(config, Path(tmp))
        print(f"  {name}: <link>.relList.supports('compression-dictionary') = {supports}; target {targets}")
        if supports is not True:
            failures.append(f"{name}: compression dictionaries are off; every stock 158 release profile has "
                            "them on (compression-dictionaries-rollout-153-release)")
        if len(targets) != 1 or not targets[0]["available-dictionary"]:
            failures.append(f"{name}: the target request named no dictionary: {targets}")
        elif not (targets[0]["accept-encoding"] or "").endswith(", dcb, dcz"):
            failures.append(f"{name}: the target request offers a dictionary but its Accept-Encoding "
                            f"{targets[0]['accept-encoding']!r} lacks stock's dcb, dcz")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: compression dictionaries are on and used, as in stock Firefox's release rollout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
