"""
Spoofed getters cost what stock Firefox's do, timed from script.

Every spoofed getter consults the config or the per-context store. When those
lookups were slow the difference was visible to a page with no reference
machine: against stock Firefox 152.0.4 on the same host, screen.width took
820-940 ns vs 130 ns, navigator.hardwareConcurrency 380-680 ns vs 45 ns, and
screen.width's cost relative to screen.orientation.type (untouched by
Camoufox) was ~10x where stock's is ~2x.

The first read in a page is checked too: it used to make a synchronous
round trip to the parent process for every unset key, so a page's first
navigator.hardwareConcurrency took 16-54 ms against stock's under 1 ms.

This guard times the same page in stock Firefox of the version in
browser/upstream.sh (--stock <firefox binary>, else downloaded and verified as
stock-gpu-parity does) and in Camoufox with a launch-level and a per-context
identity, on the same machine, and fails when a getter costs more than
SLOWER_FACTOR times stock and at least MIN_GAP_NS more. Each figure is the
fastest of several rounds over two launches, so a busy runner inflates both
browsers rather than one.

    python browser/tests/playwright/patches/getter-cost-parity.py
    python browser/tests/playwright/patches/getter-cost-parity.py --stock FIREFOX
"""

import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from helpers import resolve_binary  # noqa: E402

REPO_ROOT = HERE.parents[3]
sys.path.insert(0, str(REPO_ROOT))
from ci._util import read_upstream_sh  # noqa: E402

LAUNCHES = 2
SLOWER_FACTOR = 2.0
MIN_GAP_NS = 30.0
PAGE_TIMEOUT_S = 240
FIRST_READ_GAP_MS = 5.0

# Read once, cold, before anything else in the page touches them.
FIRST_READS = ["navigator.hardwareConcurrency", "screen.width", "screen.colorDepth",
               "devicePixelRatio", "navigator.globalPrivacyControl"]

# Spoofed getters, and controls Camoufox does not touch (a sanity check that
# the two browsers are comparable on this machine).
WINDOW = [
    "screen.width", "screen.height", "screen.availWidth", "screen.availHeight",
    "screen.colorDepth", "screen.pixelDepth", "devicePixelRatio", "innerWidth",
    "innerHeight", "outerWidth", "screenX", "history.length",
    "navigator.hardwareConcurrency", "navigator.globalPrivacyControl",
    "navigator.maxTouchPoints", "G.getParameter(G.MAX_TEXTURE_SIZE)",
    "C.measureText('mmmmmmmmmmlli').width",
    "matchMedia('(color: 8)').matches", "matchMedia('(resolution: 1dppx)').matches",
]
WORKER = [
    "navigator.hardwareConcurrency", "navigator.globalPrivacyControl",
    "new Date(1e12).getTimezoneOffset()",
]
CONTROLS = ["screen.orientation.type", "navigator.onLine"]

PAGE = """<!doctype html><meta charset=utf-8><body><script>
function bench(exprs, setup) {
  eval(setup);
  const out = {};
  const ctx = typeof C === 'undefined' ? [null, null] : [C, G];
  const mk = (e) => new Function('C', 'G', 'N',
    'let t = performance.now(); let x; for (let i = 0; i < N; i++) { x = (' + e + '); } return performance.now() - t;');
  const empty = mk('i');
  const time = (f, N) => { let b = Infinity; for (let r = 0; r < 7; r++) b = Math.min(b, f(ctx[0], ctx[1], N)); return b; };
  for (const e of exprs) {
    let f;
    try { f = mk(e); f(ctx[0], ctx[1], 10); } catch (err) { out[e] = null; continue; }
    let N = 100;
    while (N < 5e6 && f(ctx[0], ctx[1], N) < 25) N *= 4;
    out[e] = Math.max(0, time(f, N) - time(empty, N)) * 1e6 / N;
  }
  return out;
}
(async () => {
  const spec = JSON.parse(decodeURIComponent(location.hash.slice(1)));
  const first = {};
  for (const e of spec.first) {
    const f = new Function('return (' + e + ');');
    const t = performance.now();
    f();
    first[e] = performance.now() - t;
  }
  const src = 'const bench = ' + bench.toString() + '; onmessage = e => postMessage(bench(e.data, ""));';
  const w = new Worker(URL.createObjectURL(new Blob([src])));
  const worker = await new Promise(r => { w.onmessage = e => r(e.data); w.postMessage(spec.worker); });
  const win = bench(spec.window,
    "var C = document.createElement('canvas').getContext('2d'); var G = document.createElement('canvas').getContext('webgl');");
  const res = {window: win, worker, first};
  document.body.dataset.result = JSON.stringify(res);
  fetch('/result', {method: 'POST', body: JSON.stringify(res)});
})();
</script></body>"""


class Server(http.server.ThreadingHTTPServer):
    results = None


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def log_error(self, *a):
        pass

    def do_GET(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.results.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()


def stock_firefox():
    """Stock Firefox of the version Camoufox is built from: --stock, else the
    release stock-gpu-parity downloads and checks against Mozilla's signed
    SHA256SUMS."""
    spec = importlib.util.spec_from_file_location("stock_gpu_parity", HERE / "stock-gpu-parity.py")
    stock_gpu_parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stock_gpu_parity)
    return stock_gpu_parity.stock_firefox("--stock", read_upstream_sh()["version"])


def prepare_stock(binary):
    """Drop any update the reference staged. Stock Firefox downloads updates
    even with its updater deleted, and with one pending it exits at launch
    instead of loading the page."""
    root = binary.parent
    for name in ("updates", "active-update.xml", "updates.xml"):
        path = root / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def no_proxy_env():
    # A proxy in the environment makes stock Firefox stop at an auth prompt.
    return {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}


def run_stock(binary, url):
    """Starts stock Firefox on the page; returns (profile, process)."""
    prepare_stock(binary)
    profile = tempfile.mkdtemp(prefix="getter-cost-parity-")
    Path(profile, "user.js").write_text(
        'user_pref("app.update.enabled", false);\n'
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
        'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
        'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);\n'
        'user_pref("browser.aboutwelcome.enabled", false);\n')
    return profile, subprocess.Popen(
        [str(binary), "--headless", "--no-remote", "--profile", profile, url],
        env=no_proxy_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_stock(profile, proc):
    # Every process of this browser carries the throwaway profile path, and a
    # content process left behind would slow every later guard on the runner.
    subprocess.run(["pkill", "-9", "-f", profile], capture_output=True)
    proc.wait()
    shutil.rmtree(profile, ignore_errors=True)


def run_camoufox(binary, url, identity):
    """identity: "launch" (a plain page: every per-context lookup misses) or
    "context" (a per-context fingerprint: every lookup hits)."""
    from camoufox.sync_api import Camoufox
    from camoufox.fingerprints import generate_context_fingerprint

    with Camoufox(os="windows", headless=True, executable_path=str(binary),
                  i_know_what_im_doing=True) as browser:
        if identity == "context":
            fp = generate_context_fingerprint(os="windows")
            ctx = browser.new_context(**fp["context_options"])
            ctx.add_init_script(fp["init_script"])
            page = ctx.new_page()
        else:
            page = browser.new_page()
        page.goto(url)
        page.wait_for_function("document.body.dataset.result", timeout=PAGE_TIMEOUT_S * 1000)
        return json.loads(page.evaluate("document.body.dataset.result"))


def fastest(runs):
    out = {"first": {e: min(r["first"][e] for r in runs) for e in runs[0]["first"]}}
    for where in ("window", "worker"):
        out[where] = {}
        for expr in runs[0][where]:
            values = [r[where][expr] for r in runs if r[where].get(expr) is not None]
            out[where][expr] = min(values) if values else None
    return out


def main() -> int:
    camoufox_bin = resolve_binary()
    stock_bin = stock_firefox()

    server = Server(("127.0.0.1", 0), Handler)
    server.results = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    spec = json.dumps({"window": WINDOW + CONTROLS, "worker": WORKER + CONTROLS[1:], "first": FIRST_READS})
    url = f"http://127.0.0.1:{server.server_address[1]}/#" + urllib.request.quote(spec)

    stock_runs = []
    camou_runs = {"launch": [], "context": []}
    try:
        for _ in range(LAUNCHES):
            server.results = []
            profile, proc = run_stock(stock_bin, url)
            deadline = time.time() + PAGE_TIMEOUT_S
            while not server.results and time.time() < deadline:
                time.sleep(0.5)
            stop_stock(profile, proc)
            if not server.results:
                print("FAIL: stock Firefox never reported -- check is vacuous")
                return 1
            stock_runs.append(server.results[0])
            for identity, runs in camou_runs.items():
                runs.append(run_camoufox(camoufox_bin, url, identity))
    finally:
        server.shutdown()

    stock = fastest(stock_runs)
    failures = []
    for identity, runs in camou_runs.items():
        camou = fastest(runs)
        print(f"\n== Camoufox, {identity} identity")
        print(f"{'':6s} {'expression':44s} {'stock':>8s} {'camoufox':>9s}  ns/op")
        for where in ("window", "worker"):
            for expr, s in stock[where].items():
                c = camou[where].get(expr)
                if s is None or c is None:
                    print(f"{where:6s} {expr[:44]:44s} {'-':>8s} {'-':>9s}  not measurable")
                    continue
                control = expr in CONTROLS
                slow = c > SLOWER_FACTOR * s and c - s >= MIN_GAP_NS
                mark = "  <- control" if control else ("  <- SLOWER" if slow else "")
                print(f"{where:6s} {expr[:44]:44s} {s:8.0f} {c:9.0f}{mark}")
                if slow and not control:
                    failures.append(f"{identity}: {where} {expr}: {c:.0f} ns vs stock {s:.0f} ns")
                if slow and control:
                    failures.append(f"{identity}: control {where} {expr} differs ({c:.0f} vs {s:.0f} ns): "
                                    f"the two browsers are not comparable here -- check is vacuous")

        print(f"{'first read (cold)':51s} {'stock':>8s} {'camoufox':>9s}  ms")
        for expr, s in stock["first"].items():
            c = camou["first"][expr]
            slow = c - s > FIRST_READ_GAP_MS
            print(f"{expr[:51]:51s} {s:8.2f} {c:9.2f}{'  <- SLOWER' if slow else ''}")
            if slow:
                failures.append(f"{identity}: first read of {expr}: {c:.1f} ms vs stock {s:.1f} ms")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print(f"PASS: no spoofed getter costs over {SLOWER_FACTOR}x stock Firefox from script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
