"""
Terminating a worker while its main script compiles does not crash the content
process (0-playwright.patch, mEvaluatingScriptCount).

Juggler's WorkerMain.js sets a Debugger onNewScript hook, which runs JS at the end
of JS::Compile. A terminate() that arrived during the compile is handled there: the
interrupt callback notifies the worker refs, and without the patch the loader,
whose only request is already off the loaded list, shuts itself down and nulls
mWorkerRef. WorkerScriptLoader::EvaluateScript then calls mWorkerRef->Private() on
null and the content process dies with every tab in it (microsoft/playwright#42565).

The guard measures how long a worker takes to start with a tiny script and with a
large one, whose extra time is the compile, then terminates workers between the two.
On v152.0.4-beta.30 on Linux, which predates the patch, this crashes the content
process about 2.5 s after the page opens, every time.

    python browser/tests/playwright/patches/worker-terminate-mid-compile.py
"""

import http.server
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

SECONDS = 30
LOOPS = 2
MIN_COMPILE_MS = 30
MIN_TERMINATED = 30
# Expression statements, not declarations: a long `var` list spends its time in
# global declaration instantiation after the compile, and the window is missed.
SCRIPTS = {
    "/small.js": b"postMessage(1);\n",
    "/big.js": b"postMessage(1);\n" + b"0,[1,2,{a:3}];\n" * 400000,
}

PAGE = (b"""<!doctype html><meta charset=utf-8><title>starting</title><script>
const start = url => new Promise(resolve => {
  const began = performance.now();
  const w = new Worker(url);
  w.onmessage = () => { w.terminate(); resolve(performance.now() - began); };
});
async function median(url) {
  const times = [];
  for (let i = 0; i < 5; i++) times.push(await start(url));
  return times.sort((a, b) => a - b)[2];
}
let terminated = 0;
async function churn(from, to) {
  for (;;) {
    const w = new Worker('/big.js');
    await new Promise(r => setTimeout(r, from + Math.random() * (to - from)));
    w.terminate();
    terminated++;
  }
}
(async () => {
  const tiny = await median('/small.js');
  const big = await median('/big.js');
  setInterval(() => { document.title = Math.round(big - tiny) + ' ' + terminated; }, 100);
  for (let i = 0; i < LOOPS; i++) churn(tiny * 0.8, big * 1.05);
})();
</script>""").replace(b"LOOPS", str(LOOPS).encode())


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = SCRIPTS.get(self.path, PAGE)
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if body is PAGE else "text/javascript")
        self.send_header("Content-Length", str(len(body)))
        # A fresh compile every time.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    # A terminated worker's fetch breaks the pipe; the default handler prints a
    # traceback, which the guard runner keeps as the tail of the output.
    def handle_error(self, request, client_address):
        pass


def main() -> int:
    from camoufox import DefaultAddons
    from camoufox.sync_api import Camoufox

    srv = QuietServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    crashed = []
    title = ""
    try:
        with Camoufox(**launch_kwargs(exclude_addons=[DefaultAddons.UBO], i_know_what_im_doing=True)) as browser:
            page = browser.new_page()
            page.on("crash", lambda _: crashed.append("page"))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
            deadline = time.time() + SECONDS
            try:
                while time.time() < deadline and not crashed:
                    page.wait_for_timeout(250)
                    if not crashed:
                        title = page.title()
            except Exception as exc:
                # A crash mid-call surfaces as a closed target.
                crashed.append(f"{type(exc).__name__}: {str(exc).splitlines()[0]}")
    finally:
        srv.shutdown()

    if crashed:
        print(f"FAIL: the content process crashed: {crashed[0]} (last count: {title})")
        return 1
    parts = title.split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        print(f"FAIL: the page never reported a count ({title!r}) -- check is vacuous")
        return 1
    compile_ms, terminated = int(parts[0]), int(parts[1])
    print(f"terminated {terminated} workers in {SECONDS} s; the large script took {compile_ms} ms longer to start")
    if compile_ms < MIN_COMPILE_MS or terminated < MIN_TERMINATED:
        print("FAIL: too few terminations, or too short a compile to land in -- check is vacuous")
        return 1
    print("PASS: a worker terminated while its main script compiles does not crash the process.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
