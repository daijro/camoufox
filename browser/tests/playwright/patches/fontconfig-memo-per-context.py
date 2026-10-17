"""
Verify fontconfig-memo-per-context.patch: one context's font answers never
reach another context in the same content process (lang315/camoufox#83).

gfxFcPlatformFontList memoizes family-name lookups in front of the per-context
gate. Keyed by name alone, the first context to resolve a family answered for
every context sharing the process -- its allows and its refusals alike.

Contexts only share a process when the page count exceeds the content-process
pool, so an unpinned run passes by luck: on a 152.0.4 build before the fix, a
two-context probe passed 3/3 with the default pool and failed 6/6 pages in 3/3
runs with dom.ipc.processCount = 1. This guard pins the pool to one process.

  allow   context B (list allows PROBE) renders it first; context A (list
          refuses PROBE) must still refuse it
  refuse  context A resolves PROBE first; context B must still render it

    python browser/tests/playwright/patches/fontconfig-memo-per-context.py
"""

import functools
import http.server
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = "Georgia"
SAMPLE = "mmmmmmmmmmlliWWQ@#"
ONE_PROCESS = {"dom.ipc.processCount": 1, "dom.ipc.processCount.webIsolated": 1}

# rendered: PROBE changes the width against two different fallbacks the same
# way (so PROBE itself drew). refused: both widths equal their fallback alone.
MEASURE = """(probe) => {
  const s = %r;
  const c = document.createElement('canvas').getContext('2d');
  const w = (f) => { c.font = '72px ' + f; return c.measureText(s).width; };
  const cands = ['sans-serif', 'monospace', 'serif'];
  let pair = null;
  for (const a of cands) for (const b of cands) if (!pair && a !== b && w(a) !== w(b)) pair = [a, b];
  if (!pair) return {valid: false};
  const [a, b] = pair;
  const pa = w('"' + probe + '", ' + a), pb = w('"' + probe + '", ' + b);
  return {valid: true, rendered: pa === pb, refused: pa === w(a) && pb === w(b)};
}""" % SAMPLE


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def measure(browser, fp, url):
    ctx = browser.new_context(**fp["context_options"])
    ctx.add_init_script(fp["init_script"])
    page = ctx.new_page()
    page.goto(url)
    return page.evaluate(MEASURE, PROBE)


def run(binary, url, first):
    from camoufox.sync_api import Camoufox
    from camoufox.fingerprints import generate_context_fingerprint

    base = generate_context_fingerprint(os="windows")
    fonts = sorted(set(base["config"].get("fonts", [])) - {PROBE})
    refuses = generate_context_fingerprint(os="windows", config_overrides={"fonts": fonts})
    allows = generate_context_fingerprint(os="windows", config_overrides={"fonts": fonts + [PROBE]})

    with Camoufox(os="windows", fonts=fonts + [PROBE], headless=True, executable_path=str(binary),
                  firefox_user_prefs=ONE_PROCESS, i_know_what_im_doing=True) as browser:
        if first == "allow":
            b = measure(browser, allows, url)
            a = measure(browser, refuses, url)
        else:
            a = measure(browser, refuses, url)
            b = measure(browser, allows, url)
    return a, b


def main() -> int:
    binary = resolve_binary()
    site = tempfile.mkdtemp()
    Path(site, "p.html").write_text("<!doctype html><meta charset=utf-8><body>x</body>")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/p.html"

    failures = []
    try:
        for first in ("allow", "refuse"):
            a, b = run(binary, url, first)
            print(f"{first} first: refusing context {a}, allowing context {b}")
            if not (a.get("valid") and b.get("valid")):
                failures.append(f"{first}: fallback fonts measure identically -- check is vacuous")
                continue
            if not b["rendered"]:
                failures.append(f"{first}: the context whose list allows {PROBE} did not render it")
            if not a["refused"]:
                failures.append(f"{first}: the context whose list refuses {PROBE} rendered it")
    finally:
        srv.shutdown()

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print(f"PASS: {PROBE} follows each context's own list in a shared process, in both orders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
