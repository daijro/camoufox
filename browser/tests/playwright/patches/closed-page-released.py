r"""
A closed page is freed while its HTTP connections stay open (#1107).

Juggler sets each NetworkRequest as its channel's notificationCallbacks, and
Gecko keeps a connection's callbacks until the connection closes. A finished
request held its PageNetwork, and through it the page's target, browser and up
to 100 MB of response bodies, so a closed page stayed in the parent for as long
as a connection it opened. Finished requests now drop those references, as
Playwright's Juggler does (microsoft/playwright#42747).

The guard loads a page from a local HTTP/2 server, closes the page, and checks
through Marionette that a garbage collection frees its target and PageNetwork.
The server is HTTP/2 on this host's own address because that holds the
callbacks every time; HTTP/1.1, or a loopback address, does not.

    python browser/tests/playwright/patches/closed-page-released.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, launch_kwargs, marionette_args, marionette_env, own_address  # noqa: E402

SERVER = r"""
const http2 = require('node:http2'), fs = require('node:fs');
const [key, cert, host] = process.argv.slice(1);
const page = '<body>' + [...Array(6).keys()].map(i => `<script src="/a${i}.js"></script>`).join('') + '</body>';
const server = http2.createSecureServer({key: fs.readFileSync(key), cert: fs.readFileSync(cert)});
server.on('stream', (stream, headers) => {
  const root = headers[':path'] === '/';
  stream.respond({':status': 200, 'content-type': root ? 'text/html' : 'text/javascript', 'cache-control': 'no-store'});
  stream.end(root ? page : 'x'.repeat(256 * 1024));
});
server.listen(0, host, () => console.log(server.address().port));
"""

PROBE = """
const {TargetRegistry} = ChromeUtils.importESModule("resource://gre/modules/juggler/TargetRegistry.js");
const target = TargetRegistry.instance().targets().find(t => t.linkedBrowser().currentURI.spec === arguments[0]);
const network = Object.getOwnPropertySymbols(target).map(s => target[s]).find(v => v?._responseStorage);
Cu.getGlobalForObject(TargetRegistry).closedPageProbe = {target: new WeakRef(target), network: new WeakRef(network)};
return !!network;
"""
COLLECT = "Cu.forceGC(); Cu.forceCC(); Cu.forceShrinkingGC(); return 0;"
ALIVE = """
const {TargetRegistry} = ChromeUtils.importESModule("resource://gre/modules/juggler/TargetRegistry.js");
const p = Cu.getGlobalForObject(TargetRegistry).closedPageProbe;
return {target: !!p.target.deref(), network: !!p.network.deref()};
"""


def main() -> int:
    from camoufox.sync_api import Camoufox

    host = own_address()
    tmp = Path(tempfile.mkdtemp())
    key, cert = tmp / "key.pem", tmp / "cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                    "-out", str(cert), "-days", "1", "-subj", f"/CN={host}",
                    "-addext", f"subjectAltName=IP:{host}"], check=True, capture_output=True)
    server = subprocess.Popen(["node", "-e", SERVER, str(key), str(cert), host], stdout=subprocess.PIPE, text=True)
    url = f"https://{host}:{server.stdout.readline().strip()}/"
    port = free_port()
    try:
        with Camoufox(**launch_kwargs(args=marionette_args(), env=marionette_env(), firefox_user_prefs={"marionette.port": port},
                                      i_know_what_im_doing=True)) as browser:
            # One context that outlives the page, as in a long-running crawler:
            # closing a context closes its connections.
            context = browser.new_context(ignore_https_errors=True)
            context.new_page()
            page = context.new_page()
            page.goto(url, wait_until="load")
            m = Marionette(port)
            try:
                assert m.call("WebDriver:ExecuteScript", {"script": PROBE, "args": [url]})["value"], "no PageNetwork"
                page.close()
                # Marionette may have been on the closed page's window.
                m.call("WebDriver:SwitchToWindow", {"handle": m.call("WebDriver:GetWindowHandles", {})[0]})
                for _ in range(5):
                    m.js(COLLECT)
                    time.sleep(0.2)
                alive = m.js(ALIVE)
            finally:
                m.close()
            context.close()
    finally:
        server.kill()

    print(f"  after close and GC: target alive={alive['target']}, PageNetwork alive={alive['network']}")
    if alive["target"] or alive["network"]:
        print("FAIL: a closed page stays in the parent while its connections are open")
        return 1
    print("PASS: a closed page is freed while its connections stay open.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
