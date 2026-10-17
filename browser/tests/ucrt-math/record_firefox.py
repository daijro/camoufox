"""Record what stock Firefox on Windows returns for probe.js (run on Windows).

    py browser/tests/ucrt-math/record_firefox.py "C:\\Program Files\\Mozilla Firefox\\firefox.exe"

Writes browser/tests/playwright/patches/assets/windows-crt-math.json, the
reference the windows-crt-math patch guard compares Camoufox against: a sample
of inputs.py, and what Firefox's Math.sin/cos/tan/pow and ** gave for them,
cold, hot and constant-folded. Use the Firefox version browser/upstream.sh pins.
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
from inputs import pow_inputs, trig_inputs  # noqa: E402

OUT = HERE.parent / "playwright" / "patches" / "assets" / "windows-crt-math.json"
STRIDE = 20

# pow_inputs() indices where glibc's pow (2.36) and ucrtbase's differ in the
# last bit. pow is accurate enough on both that a stride sample alone almost
# never lands on one, and then the guard could not catch a broken pow.
POW_DISAGREE = [15, 1756, 2711, 3081, 3717, 5118, 5136, 5619, 6102, 8348, 9586, 9598, 9756, 10017, 10074, 10629, 10688, 10689, 10691, 11675, 12521, 12985, 13126, 13181, 13356, 13683, 13890, 14171, 15257, 15792, 16065, 16066, 16694, 17079, 17647, 17932, 18078, 18768, 18786, 19056, 20004, 21668, 21734, 21963, 22786, 23530, 23681]


def sample():
    return {
        "trig": [format(b, "x") for b in trig_inputs()[::STRIDE]],
        "pow": [[format(a, "x"), format(b, "x")]
                for a, b in pow_inputs()[::STRIDE] + [pow_inputs()[i] for i in POW_DISAGREE]],
    }


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
    OUT.write_text(json.dumps({"firefox": version, "stride": STRIDE, "input": data, "expected": got}))
    print(f"{len(data['trig'])} trig and {len(data['pow'])} pow inputs from {version} -> {OUT}")


if __name__ == "__main__":
    main()
