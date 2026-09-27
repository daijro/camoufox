r"""
The GPU probes ship, so the browser decides about graphics the way stock does.

Firefox runs two small helper binaries at startup -- `glxtest` (GL/EGL) and
`vaapitest` (video decode) -- and feeds what they report into nsIGfxInfo. Without
them gfxInfo has nothing, and the driver blocklist refuses **every** WebGL
context:

    WebGL creation failed:
    * WebglAllowWindowsNativeGl:false restricts context creation on this system.
    * Exhausted GL driver options. (FEATURE_FAILURE_WEBGL_EXHAUSTED_DRIVERS)

`scripts/package.py` used to drop both as "unneeded" (~50 KB), and the launcher
covered for it with `webgl.force-enabled`, so the breakage only showed on a
launch that did not go through pythonlib -- measured 2026-09-18: stock Firefox
152.0.4 on this machine returned a full WebGL 2.0 context from the real GPU and
camoufox returned `null` from `canvas.getContext('webgl')`.

Three checks, because each alone can pass while the others are broken: the
packaging list must not name them, the build under test must have them beside
the binary, and a bare launch -- no pythonlib, so no `webgl.force-enabled` --
must still get a context.

    python tests/patches/gfx-probes-packaged.py
"""

import http.server
import json
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBES = ("glxtest", "vaapitest")
LOAD_TIMEOUT_S = 90
ATTEMPTS = 2

PAGE = b"""<!doctype html><meta charset=utf-8><title>gfx-probes</title><body><script>
const out = {};
const c = document.createElement('canvas');
c.addEventListener('webglcontextcreationerror', e => { out.error = e.statusMessage; });
const gl = c.getContext('webgl2') || c.getContext('webgl');
out.context = !!gl;
if (gl) {
  out.version = gl.getParameter(gl.VERSION);
  out.renderer = gl.getParameter(gl.RENDERER);
  out.extensions = (gl.getSupportedExtensions() || []).length;
}
fetch('/report', {method: 'POST', body: JSON.stringify(out)});
</script></body>"""


def serve():
    """The page, plus the endpoint it posts its answer back to."""
    received = {}
    done = threading.Event()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                received.update(json.loads(body))
            except ValueError:
                received["_parse_error"] = body[:200].decode("utf-8", "replace")
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1], received, done


def packaging_drops_probes() -> list:
    """The names package.py refuses to ship, as the source declares them."""
    text = (REPO_ROOT / "scripts" / "package.py").read_text()
    unneeded = text.split("UNNEEDED_PATHS = {", 1)[1].split("}", 1)[0]
    return [name for name in PROBES if f"'{name}'" in unneeded or f'"{name}"' in unneeded]


def webgl_report(binary: Path) -> dict:
    """What a plain WebGL request does in a bare launch of this build."""
    srv, port, received, done = serve()
    profile = tempfile.mkdtemp(prefix="gfxprobe-")
    Path(profile, "user.js").write_text(
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
        'user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);\n'
    )
    stderr = Path(profile, "stderr.log")
    with stderr.open("wb") as err:
        proc = subprocess.Popen(
            [str(binary), "-headless", "-no-remote", "-profile", profile,
             f"http://127.0.0.1:{port}/"],
            stdout=subprocess.DEVNULL, stderr=err,
        )
    try:
        if done.wait(LOAD_TIMEOUT_S):
            report = dict(received)
        else:
            report = {"context": None, "note": f"no report within {LOAD_TIMEOUT_S}s"}
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        srv.shutdown()
    # What the probes said, if they said anything: an empty gfxInfo reads the
    # same to the page whether glxtest is missing or ran and failed.
    report["gfx_stderr"] = [
        line for line in stderr.read_text(errors="replace").splitlines()
        if "glxtest" in line or "vaapitest" in line or "GfxInfo" in line
    ][-10:]
    shutil.rmtree(profile, ignore_errors=True)
    return report


def main() -> int:
    failures = []

    dropped = packaging_drops_probes()
    if dropped:
        failures.append(f"scripts/package.py drops {', '.join(dropped)} from the package")

    binary = resolve_binary()
    install = binary.parent
    missing = [name for name in PROBES if not (install / name).exists()]
    if missing:
        failures.append(f"{install} has no {', '.join(missing)}")

    # Only the blocklist refusal is this guard's business. A machine with no
    # usable GL at all (a bare CI container) fails for its own reasons and would
    # otherwise turn this into a flaky gate; the missing-probe defect has a
    # signature, so match that. The signature is really "gfxInfo is empty",
    # which a present glxtest that failed or timed out on a loaded runner also
    # produces -- once in a while, where missing probes produce it every launch
    # -- so a refusal gets one more launch before it counts.
    for attempt in range(1, ATTEMPTS + 1):
        report = webgl_report(binary)
        error = report.get("error") or ""
        blocklisted = report.get("context") is not True and (
            "Exhausted GL driver options" in error or "restricts context creation" in error)
        if not blocklisted or attempt == ATTEMPTS:
            break
        print(f"NOTE: launch {attempt} refused by the blocklist, launching again: {error}")
    if report.get("context") is not True:
        if blocklisted:
            failures.append(f"a bare launch was refused a WebGL context by the blocklist: {error}")
        else:
            print(f"NOTE: no WebGL context here, and not from the blocklist: "
                  f"{error or report.get('note') or report}")

    print(json.dumps({"packaging_drops": dropped, "missing_from_install": missing,
                      "webgl": report}, indent=2))
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: glxtest and vaapitest ship, and WebGL works without a pref forcing it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
