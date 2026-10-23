"""Record what stock Firefox on Windows returns for probe.js (run on Windows).

    py browser/tests/ucrt-math/record_firefox.py "C:\\Program Files\\Mozilla Firefox\\firefox.exe"

Writes browser/tests/playwright/patches/assets/windows-crt-math.json, the
reference the windows-crt-math patch guard compares Camoufox against: a sample
of inputs.py, and what Firefox's Math.sin/cos/tan/pow and ** gave for them,
cold, hot and constant-folded. Windows gives the same results cold and hot, and
this fails if it does not. Use the Firefox version browser/upstream.sh pins;
docs/HOST-PARITY.md says what the file in the repository was recorded on.
"""

import http.server
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inputs import TRIG_SPECIAL, pow_inputs, trig_inputs  # noqa: E402

OUT = HERE.parent / "playwright" / "patches" / "assets" / "windows-crt-math.json"
STRIDE = 20

# pow_inputs() indices, among those Math.pow sends to the CRT, where Windows
# 11's pow differs in the last bit from glibc 2.43's (the first eight) or from
# the pow of Windows 10 and Windows 11 before 24H2 (ucrtbase 10.0.22621). pow
# is accurate enough that a stride sample alone almost never lands on one, and
# then the guard could not catch a wrong pow.
POW_DISAGREE = [1125, 4158, 5136, 5439, 5619, 13356, 20004, 21668,
                15, 1756, 2711, 3081, 3717, 5118, 6102, 8348, 9598, 10629, 10688, 10689, 10691,
                12985, 13181, 13890, 15257, 16065, 16066, 16694, 17647, 18786, 19056, 21963, 23530]


def sample():
    return {
        "trig": [format(b, "x") for b in trig_inputs()[::STRIDE] + TRIG_SPECIAL],
        "pow": [[format(a, "x"), format(b, "x")]
                for a, b in pow_inputs()[::STRIDE] + [pow_inputs()[i] for i in POW_DISAGREE]],
    }


def reference(got):
    """What the windows-crt-math guard compares against: one set of results,
    since Windows gives the same cold and hot, and the constant-folded ones."""
    if got["cold"] != got["hot"]:
        sys.exit("Windows Firefox gave different results cold and hot; the guard assumes it does not")
    return {"results": got["cold"], "constants": got["constants"]}


def main():
    firefox = sys.argv[1]
    data = sample()
    page = ("<!doctype html><meta charset=utf-8><script>"
            f"const result = ({(HERE / 'probe.js').read_text()})({json.dumps(data)});"
            "fetch('/', {method: 'POST', body: JSON.stringify(result)});</script>").encode()
    got = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            got.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()
            done.set()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Firefox's child processes outlive the parent for a moment and hold files in
    # the profile, so cleanup errors are ignored rather than fatal.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        (Path(profile) / "user.js").write_text(
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
            'user_pref("app.update.enabled", false);\n')
        proc = subprocess.Popen([firefox, "-headless", "-no-remote", "-profile", profile,
                                 f"http://127.0.0.1:{server.server_address[1]}/"])
        try:
            if not done.wait(120):
                sys.exit("Firefox did not report back within 120 s")
        finally:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            proc.wait()
    version = subprocess.run([firefox, "--version"], capture_output=True, text=True).stdout.strip()
    OUT.write_text(json.dumps({"firefox": version, "stride": STRIDE, "input": data,
                               "expected": reference(got)}))
    print(f"{len(data['trig'])} trig and {len(data['pow'])} pow inputs from {version} -> {OUT}")


if __name__ == "__main__":
    main()
