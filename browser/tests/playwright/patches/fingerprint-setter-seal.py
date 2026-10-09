"""
Verify that the per-context fingerprint setters are gone before page script runs.

Camoufox applies a per-context fingerprint through a set of chrome-ish helpers
on window -- setNavigatorPlatform(), setTimezone(), setWebGLRenderer() and a
dozen more. They are configuration API for the automation side: an init script
calls them at document-start, and each one used to remove itself from window on
its way out.

Self-removal only covered the setters that were actually called:

  * a fingerprint that leaves a value alone never calls that value's setter, so
    it stayed on window -- setTimezone (no timezone configured) and
    setWebRTCIPv6 (never emitted at all) leaked on every single context;
  * a launch that registers no init script at all leaked all of them. That is
    `Camoufox()` followed by `browser.new_page()`, the documented default --
    there, fingerprints come from CAMOU_CONFIG in C++ and nothing ever touches
    a setter, so nothing ever self-destructed.

Window properties that no other Firefox build has are a sharper fingerprint
than any of the values they were hiding, and page script could not
only see them but call them: `window.setNavigatorHardwareConcurrency(999)` from
a page moved navigator.hardwareConcurrency to 999.

Juggler now seals the whole set once init scripts have run and before page
script gets a turn (FrameTree._onGlobalObjectCleared -> camouSealFingerprintSetters).

This measures what the PAGE sees. An inline <script> in the served document
reports through document.title; page.evaluate() runs in the isolated world and
is exactly the probe that cannot see this.

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python browser/tests/playwright/patches/fingerprint-setter-seal.py

What PASS means:
    * none of the setters is visible to page script, in the default
      launch path or through NewContext();
    * none of them is callable either -- a name can be missing from `for...in`
      and still work when called;
    * sealing did not cost the spoofing. Two contexts asking for different
      operating systems each get their own fingerprint, and an init script
      registered after the page already exists still applies on the next
      navigation. A seal keyed on the browsing context rather than the window
      fails both: it fires on the initial about:blank, and every document after
      that comes up with the launch-level fingerprint instead of its own.
"""

import http.server
import json
import socketserver
import sys
import threading

SETTERS = [
    "setNavigatorPlatform",
    "setNavigatorOscpu",
    "setNavigatorHardwareConcurrency",
    "setNavigatorUserAgent",
    "setScreenDimensions",
    "setScreenColorDepth",
    "setWebGLVendor",
    "setWebGLRenderer",
    "setWebRTCIPv4",
    "setWebRTCIPv6",
    "setFontList",
    "setAudioFingerprintSeed",
    "setSpeechVoices",
    "setTimezone",
]

# The page reports from its own world. `visible` is what a `for...in` sweep
# finds, `callable` is the stronger check -- a deleted name that still resolves
# on call is just as good a signal for a detector.
PAGE = """<!DOCTYPE html><html><head><title>pending</title></head><body>
<script>
  var names = %s;
  var visible = [], callable = [];
  for (var i = 0; i < names.length; i++) {
    var n = names[i];
    if (n in window) visible.push(n);
    if (typeof window[n] === 'function') callable.push(n);
  }
  var enumerated = [];
  for (var k in window) if (names.indexOf(k) !== -1) enumerated.push(k);
  document.title = JSON.stringify({
    visible: visible, callable: callable, enumerated: enumerated,
    platform: navigator.platform, width: screen.width,
    ua: navigator.userAgent
  });
</script>
</body></html>""" % json.dumps(SETTERS)


def serve():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def probe(context, url):
    page = context.new_page()
    page.goto(url)
    page.wait_for_function("document.title !== 'pending'", timeout=10000)
    return json.loads(page.title())


def main():
    from camoufox.sync_api import Camoufox
    from camoufox.fingerprints import generate_context_fingerprint
    from helpers import launch_kwargs

    httpd, url = serve()
    results = []
    try:
        with Camoufox(**launch_kwargs()) as browser:
            # The documented default: no init script anywhere, fingerprints come
            # from CAMOU_CONFIG in C++. Nothing ever calls a setter here, so this
            # is the launch that used to leak all of them.
            results.append(("default launch", probe(browser.new_context(), url), None))

            # Two contexts with deliberately different identities. The seal is
            # per window; if it were per browsing context it would fire on the
            # first about:blank and every later navigation would come up with
            # the launch-level fingerprint instead of its own.
            for tag, target in (("context/windows", "windows"), ("context/macos", "macos")):
                fp = generate_context_fingerprint(os=target)
                ctx = browser.new_context(**fp["context_options"])
                ctx.add_init_script(fp["init_script"])
                want = (fp["config"].get("navigator.platform"),
                        fp["config"].get("screen.width"))
                results.append((tag, probe(ctx, url), want))

            # add_init_script() registered *after* the page exists. The initial
            # about:blank has already been sealed by then, and the script only
            # runs on the navigation after it -- a fresh window, so a fresh
            # configuration window.
            fp = generate_context_fingerprint(os="macos")
            ctx = browser.new_context(**fp["context_options"])
            page = ctx.new_page()
            page.add_init_script(fp["init_script"])
            page.goto(url)
            page.wait_for_function("document.title !== 'pending'", timeout=10000)
            late = json.loads(page.title())
            results.append(("late add_init_script", late,
                            (fp["config"].get("navigator.platform"),
                             fp["config"].get("screen.width"))))
    finally:
        httpd.shutdown()

    failures = []
    for label, r, want in results:
        for field in ("visible", "callable", "enumerated"):
            leaked = r[field]
            print(f"  [{'PASS' if not leaked else 'FAIL'}] {label}: {field:<11} "
                  f"{len(leaked)}{'' if not leaked else ' -> ' + str(leaked)}")
            if leaked:
                failures.append(f"{label}: {field} leaked {leaked}")
        if want is not None:
            got = (r["platform"], r["width"])
            ok = got == want
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}: fingerprint applied "
                  f"want={want} got={got}")
            if not ok:
                failures.append(f"{label}: wanted {want}, got {got}")

    print()
    if failures:
        print(f"FAILED ({len(failures)})")
        for f in failures:
            print("  -", f)
        return 1
    print("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
