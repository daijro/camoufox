r"""
Headless Camoufox has the WebGL a headed browser on Xvfb has: Mesa's llvmpipe.

Firefox's GPU probe (`gfxtest glx`) talks to the X server unless Wayland is in
use. A headless launch with no display therefore gets an empty gfxInfo, the
driver blocklist refuses every GL feature, and the page sees

    canvas.getContext('webgl')  -> null
    WebGL creation failed:
    * WebglAllowWindowsNativeGl:false restricts context creation on this system.
    * Exhausted GL driver options. (FEATURE_FAILURE_WEBGL_EXHAUSTED_DRIVERS)

and WebGL 2 "AllowWebgl2:false". Stock Firefox 158 headless does the same, but
Camoufox headless claims a desktop browser, and a desktop Firefox without WebGL
is rare. The same empty gfxInfo also drops H264 from WebRTC's codec list.
headless-software-webgl.patch probes through EGL with Mesa's software GL when
headless and there is no display, and keeps that WebGL on Mesa's software EGL
device. A headless launch that still has a display uses it, as stock does.

The check: one bare launch -headless (no DISPLAY, no WAYLAND_DISPLAY) and one
bare launch headed on a private Xvfb, same binary. Headless must get a WebGL 1
and 2 context whose parameters, extensions, precisions, attributes and a
cleared pixel equal the Xvfb launch's, and the same WebRTC video codecs.

    python browser/tests/playwright/patches/headless-software-webgl.py
"""

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

LOAD_TIMEOUT_S = 90

PAGE = b"""<!doctype html><meta charset=utf-8><title>headless-webgl</title><body><script>
setTimeout(() => {
  const out = {};
  for (const k of ['webgl', 'webgl2']) {
    const c = document.createElement('canvas');
    let err = null;
    c.addEventListener('webglcontextcreationerror', e => { err = e.statusMessage; });
    const g = c.getContext(k);
    if (!g) { out[k] = {error: err}; continue; }
    const p = {};
    for (const n in Object.getPrototypeOf(g)) {
      const v = g[n];
      if (typeof v !== 'number' || !/^(MAX_|ALIASED_|SUBPIXEL|SAMPLES|SAMPLE_BUFFERS|(RED|GREEN|BLUE|ALPHA|DEPTH|STENCIL)_BITS|SHADING|VERSION|VENDOR|RENDERER|MIN_|IMPLEMENTATION)/.test(n)) continue;
      const x = g.getParameter(v);
      p[n] = x && typeof x === 'object' ? Array.from(x) : x;
    }
    p.extensions = g.getSupportedExtensions();
    p.attributes = g.getContextAttributes();
    p.precision = [];
    for (const s of [g.VERTEX_SHADER, g.FRAGMENT_SHADER])
      for (const t of [g.LOW_FLOAT, g.MEDIUM_FLOAT, g.HIGH_FLOAT, g.LOW_INT, g.MEDIUM_INT, g.HIGH_INT]) {
        const f = g.getShaderPrecisionFormat(s, t); p.precision.push([f.rangeMin, f.rangeMax, f.precision]);
      }
    const d = g.getExtension('WEBGL_debug_renderer_info');
    if (d) { p.UNMASKED_RENDERER = g.getParameter(d.UNMASKED_RENDERER_WEBGL); p.UNMASKED_VENDOR = g.getParameter(d.UNMASKED_VENDOR_WEBGL); }
    g.clearColor(0.2, 0.4, 0.6, 0.8); g.clear(g.COLOR_BUFFER_BIT);
    const px = new Uint8Array(4); g.readPixels(0, 0, 1, 1, g.RGBA, g.UNSIGNED_BYTE, px); p.pixel = Array.from(px);
    out[k] = p;
  }
  out.rtpVideo = RTCRtpReceiver.getCapabilities('video').codecs.map(c => c.mimeType).join(' ');
  fetch('/report', {method: 'POST', body: JSON.stringify(out)});
}, 1500);
</script></body>"""


def serve():
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
            received.update(json.loads(body))
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *args):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1], received, done


def report(binary: Path, display: str | None) -> dict:
    """What the page sees in a bare launch: -headless when `display` is None, else headed on it."""
    srv, port, received, done = serve()
    profile = tempfile.mkdtemp(prefix="headless-webgl-")
    Path(profile, "user.js").write_text(
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
        'user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);\n')
    env = {k: v for k, v in os.environ.items()
           if k not in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "MOZ_HEADLESS", "LIBGL_ALWAYS_SOFTWARE")}
    if display:
        env["DISPLAY"] = display
    args = [str(binary), *([] if display else ["-headless"]), "-no-remote", "-profile", profile,
            f"http://127.0.0.1:{port}/"]
    proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        out = dict(received) if done.wait(LOAD_TIMEOUT_S) else {"note": f"no report within {LOAD_TIMEOUT_S}s"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
    return out


def main() -> int:
    binary = resolve_binary()
    headless = report(binary, None)
    with hidden_display("1920x1080") as display:
        headed = report(binary, display)

    if not isinstance(headed.get("webgl"), dict) or "error" in headed["webgl"]:
        print(f"FAIL: no WebGL headed on Xvfb, nothing to compare: {headed}")
        return 1

    failures = []
    for k in ("webgl", "webgl2"):
        h, x = headless.get(k) or {}, headed.get(k) or {}
        if "error" in h or not h:
            failures.append(f"headless {k}: no context ({h.get('error') or headless.get('note')})")
            continue
        for key in sorted(set(h) | set(x)):
            if h.get(key) != x.get(key):
                failures.append(f"headless {k} {key}={json.dumps(h.get(key))[:120]} "
                                f"but headed on Xvfb {json.dumps(x.get(key))[:120]}")
    if headless.get("rtpVideo") != headed.get("rtpVideo"):
        failures.append(f"WebRTC video codecs headless [{headless.get('rtpVideo')}] "
                        f"but headed on Xvfb [{headed.get('rtpVideo')}]")

    print(json.dumps({"headless": {k: (headless.get(k) or {}).get("UNMASKED_RENDERER", headless.get(k))
                                   for k in ("webgl", "webgl2")},
                      "xvfb": {k: (headed.get(k) or {}).get("UNMASKED_RENDERER") for k in ("webgl", "webgl2")}},
                     indent=2))
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: headless WebGL (and WebRTC H264) equal a headed launch on Xvfb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
