"""
Verify worker reads of per-context values (anti-font-fingerprinting.patch,
RoverfoxStorageManager).

  values  a worker in a macOS context of a Windows launch reports the context's
          navigator.platform, hardwareConcurrency and timezone, like its window
  race    workers reading navigator in a tight loop while other contexts are
          created (each one's values reach every process as new prefs) do not
          crash the content process

Workers used to fall through to libpref, whose table is main-thread only and
looked up without a lock in a release build. On v152.0.4-beta.30, which reads
it, the race case crashed the content process in 21 of 21 runs, after 0-46
contexts; with no workers the same loop held for 60 s (67-80 contexts).

    python tests/patches/worker-config-reads.py
"""

import functools
import http.server
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# Four workers for 60 s: two for 30 s crashed beta.30 in only 7 of 11 runs.
RACE_SECONDS = 60
WORKERS = 4
# One content process, so every context's prefs land in the workers' process.
ONE_PROCESS = {"dom.ipc.processCount": 1, "dom.ipc.processCount.webIsolated": 1}

VALUES = """async () => {
  const read = () => ({platform: navigator.platform, cores: navigator.hardwareConcurrency,
                       tz: Intl.DateTimeFormat().resolvedOptions().timeZone});
  const code = 'postMessage((' + read.toString() + ')())';
  const w = new Worker(URL.createObjectURL(new Blob([code])));
  const worker = await new Promise(r => { w.onmessage = e => r(e.data); });
  return {window: read(), worker};
}"""

# Workers report their count at most every 100 ms. Posting per fixed batch of
# reads flooded the page's main thread once reads got fast (~16k messages/s
# at ~1e9 reads per 30 s), and on a 4-core runner navigation starved and
# timed out -- the harness failing, not the browser.
SPIN = """(n) => {
  window.__reads = 0;
  const code = 'let c = 0, last = performance.now(); for(;;){ for(let i=0;i<2000;i++){'
             + ' navigator.hardwareConcurrency; navigator.platform; navigator.userAgent; navigator.language; }'
             + ' c += 2000; const now = performance.now();'
             + ' if (now - last >= 100) { postMessage(c); c = 0; last = now; } }';
  for (let i = 0; i < n; i++) {
    const w = new Worker(URL.createObjectURL(new Blob([code])));
    w.onmessage = (e) => { window.__reads += e.data; };
  }
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def log_error(self, *a):
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    # A page torn down mid-response (a crashed or closed context) breaks the
    # pipe; the default handler prints a traceback, which the guard runner
    # keeps as the tail of the output in place of the actual verdict.
    def handle_error(self, request, client_address):
        pass


def check_values(binary, url, failures):
    from camoufox.sync_api import Camoufox
    from camoufox.fingerprints import generate_context_fingerprint

    fp = generate_context_fingerprint(os="macos", timezone="Asia/Tokyo")
    with Camoufox(os="windows", headless=True, executable_path=str(binary),
                  i_know_what_im_doing=True) as browser:
        ctx = browser.new_context(**fp["context_options"])
        ctx.add_init_script(fp["init_script"])
        page = ctx.new_page()
        page.goto(url)
        out = page.evaluate(VALUES)
    print(f"values: {out}")
    if out["window"]["platform"] != "MacIntel" or out["window"]["tz"] != "Asia/Tokyo":
        failures.append(f"values: the context's own values did not apply to its window -- check is vacuous: {out}")
    elif out["worker"] != out["window"]:
        failures.append(f"values: worker {out['worker']} differs from window {out['window']}")


def check_race(binary, url, failures):
    from camoufox import DefaultAddons
    from camoufox.sync_api import Camoufox
    from camoufox.fingerprints import generate_context_fingerprint

    fps = [generate_context_fingerprint(os=o) for o in ("macos", "linux", "windows")]
    crashed = []
    errors = []
    created = 0
    gotos = []
    reads = 0
    # Without uBlock Origin, which is reinstalled for every window (#185): on
    # beta.30 the fourth context's navigation hung for 45 s in 3 of 3 runs even
    # with no workers, a harness error that would hide the race.
    with Camoufox(os="windows", headless=True, executable_path=str(binary),
                  firefox_user_prefs=ONE_PROCESS, exclude_addons=[DefaultAddons.UBO],
                  i_know_what_im_doing=True) as browser:
        spin = browser.new_page()
        spin.on("crash", lambda _: crashed.append("spinning page"))
        spin.goto(url)
        spin.evaluate(SPIN, WORKERS)
        deadline = time.time() + RACE_SECONDS
        try:
            while time.time() < deadline and not crashed:
                fp = fps[created % len(fps)]
                ctx = browser.new_context(**fp["context_options"])
                ctx.add_init_script(fp["init_script"])
                page = ctx.new_page()
                page.on("crash", lambda _: crashed.append("new context's page"))
                started = time.monotonic()
                page.goto(url, timeout=45000)
                gotos.append(time.monotonic() - started)
                ctx.close()
                created += 1
            if not crashed:
                reads = spin.evaluate("window.__reads")
        except Exception as exc:
            # A crash mid-call surfaces as a closed target; anything else (a
            # timeout) is the harness, not the race, and is reported as such.
            first = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            (crashed if "closed" in first.lower() or "crash" in first.lower() else errors).append(first)
    # A starved machine slows every navigation; a stall shows as fast ones
    # followed by one that never finishes.
    slowest = f"{max(gotos):.2f}" if gotos else "-"
    print(f"race: {created} contexts in {RACE_SECONDS} s (slowest goto {slowest} s), {reads} worker reads,"
          f" crashed: {crashed or 'no'}" + (f", harness errors: {errors}" if errors else ""))
    if crashed:
        failures.append(f"race: content process crashed after {created} contexts ({crashed[0]})")
    elif errors:
        failures.append(f"race: harness error after {created} contexts ({errors[0]}) -- check is vacuous")
    elif created < 10 or reads == 0:
        failures.append(f"race: {created} contexts / {reads} worker reads -- check is vacuous")


def main() -> int:
    binary = resolve_binary()
    site = tempfile.mkdtemp()
    Path(site, "p.html").write_text("<!doctype html><meta charset=utf-8><body>x</body>")
    srv = QuietServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/p.html"

    failures = []
    try:
        check_values(binary, url, failures)
        check_race(binary, url, failures)
    finally:
        srv.shutdown()

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: workers read their context's values and survive concurrent context creation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
