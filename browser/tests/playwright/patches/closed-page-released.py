r"""
A closed page is freed while its HTTP connections stay open (#1107), and while
a request it made is suspended.

Juggler sets each NetworkRequest as its channel's notificationCallbacks, and
Gecko keeps a connection's callbacks until the connection closes. A finished
request held its PageNetwork, and through it the page's target, browser and up
to 100 MB of response bodies, so a closed page stayed in the parent for as long
as a connection it opened. Finished requests now drop those references, as
Playwright's Juggler does (microsoft/playwright#42747).

A request that never finishes held its page the same way. A channel cancelled
while it is suspended -- by an extension's blocking webRequest listener, as
uBlock Origin's is while it loads its lists -- does not stop until it is
resumed. CI caught it about once in 60 runs: the page's favicon, aborted and
still pending, held the page. A destroyed page's requests now drop it too.

The guard loads a page from a local HTTP/2 server and closes it, then loads a
second page, suspends one of its requests, and closes that, and checks through
Marionette that garbage collection frees each page's target and PageNetwork.
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
const scripts = [...Array(6).keys()].map(i => `<script src="/a${i}.js"></script>`).join('');
const pages = {'/': `<body>${scripts}</body>`, '/held': '<body><img src="/held.png"></body>'};
const server = http2.createSecureServer({key: fs.readFileSync(key), cert: fs.readFileSync(cert)});
server.on('stream', (stream, headers) => {
  const page = pages[headers[':path']];
  stream.respond({':status': 200, 'content-type': page ? 'text/html' : 'text/javascript', 'cache-control': 'no-store'});
  stream.end(page || 'x'.repeat(256 * 1024));
});
server.listen(0, host, () => console.log(server.address().port));
"""

# Suspends /held.png as a blocking webRequest listener would, until RESUME.
SUSPEND = """
const g = Cu.getGlobalForObject(Services);
g.heldChannels = [];
g.heldObserver = {observe(channel) {
  channel.QueryInterface(Ci.nsIHttpChannel);
  if (channel.URI.filePath === '/held.png') { channel.suspend(); g.heldChannels.push(channel); }
}};
Services.obs.addObserver(g.heldObserver, 'http-on-modify-request');
return 0;
"""
HELD = "return Cu.getGlobalForObject(Services).heldChannels.length;"
RESUME = """
const g = Cu.getGlobalForObject(Services);
Services.obs.removeObserver(g.heldObserver, 'http-on-modify-request');
for (const channel of g.heldChannels) channel.resume();
return 0;
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
# A page that is freed is freed by the first collection; one that is held stays
# held for as long as its connection or its suspended request, which outlast
# this. The deadline is for a slow runner, not a fix for a slow free.
FREE_WITHIN = 10


def close_and_collect(m, page, url):
    assert m.call("WebDriver:ExecuteScript", {"script": PROBE, "args": [url]})["value"], "no PageNetwork"
    page.close()
    # Marionette may have been on the closed page's window.
    m.call("WebDriver:SwitchToWindow", {"handle": m.call("WebDriver:GetWindowHandles", {})[0]})
    deadline = time.monotonic() + FREE_WITHIN
    while True:
        m.js(COLLECT)
        alive = m.js(ALIVE)
        if not (alive["target"] or alive["network"]) or time.monotonic() > deadline:
            return alive
        time.sleep(0.2)


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
    results = {}
    try:
        with Camoufox(**launch_kwargs(args=marionette_args(), env=marionette_env(), firefox_user_prefs={"marionette.port": port},
                                      i_know_what_im_doing=True)) as browser:
            # One context that outlives the pages, as in a long-running crawler:
            # closing a context closes its connections.
            context = browser.new_context(ignore_https_errors=True)
            context.new_page()
            m = Marionette(port)
            try:
                page = context.new_page()
                page.goto(url, wait_until="load")
                results["finished requests, connections open"] = close_and_collect(m, page, url)

                m.js(SUSPEND)
                page = context.new_page()
                # The suspended image holds the load event.
                page.goto(url + "held", wait_until="domcontentloaded")
                deadline = time.monotonic() + 30
                while not m.js(HELD):
                    assert time.monotonic() < deadline, "the image request never started"
                    time.sleep(0.1)
                results["a request suspended"] = close_and_collect(m, page, url + "held")
                m.js(RESUME)
            finally:
                m.close()
            context.close()
    finally:
        server.kill()

    failed = False
    for case, alive in results.items():
        held = alive["target"] or alive["network"]
        failed |= held
        print(f"  {case}: after close and GC, target alive={alive['target']}, PageNetwork alive={alive['network']}"
              f"{'  <-- held' if held else ''}")
    if failed:
        print("FAIL: a closed page stays in the parent")
        return 1
    print("PASS: a closed page is freed while its connections stay open or a request of its is suspended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
