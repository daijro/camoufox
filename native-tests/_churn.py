"""A local page that churns one browser mechanism, hard, offline.

daijro/camoufox#762 needs an ad-heavy page and a couple of minutes to reach 15 GB.
That is not a test. But the *shape* of a runaway is reproducible without the ads:
drive one mechanism thousands of times and watch whether the content process's
memory scales with the count.

The theory this is built to test is that Camoufox adds per-something state that
stock Firefox does not have -- an isolated world, a canvas noise seed, a font
list -- and that something churning fast enough (an ad stack creating and
destroying iframes, compiling scripts, drawing to canvases) accumulates it.

Each churn page hammers exactly one mechanism, so a leak points at a culprit
instead of just saying "memory grew". Everything is served from loopback: no
network, no ad rotation, byte-identical every run, and fast enough to sit in CI.
"""

from __future__ import annotations

import http.server
import threading
from typing import Dict

_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>churn: {name}</title>
<body>
<div id="host"></div>
<script>
window.__done = false;
window.__iterations = 0;
async function run() {{
  const N = Number(new URLSearchParams(location.search).get('n') || '{default_n}');
  for (let i = 0; i < N; i++) {{
    {body}
    window.__iterations = i + 1;
    // Yield often enough that the parent can collect and the page stays alive.
    if (i % 25 === 0) await new Promise(r => setTimeout(r, 0));
  }}
  window.__done = true;
}}
run();
</script>
</body>
"""

# Each body runs once per iteration and must clean up after itself. Anything
# that grows here is the browser's doing, not the page's.
BODIES: Dict[str, str] = {
    # Ad stacks are iframe machines. Every document creates a fresh scope, and
    # under Camoufox a fresh isolated world alongside it.
    "iframe": """
    const f = document.createElement('iframe');
    f.srcdoc = '<script>var x = 1;<\\/script>';
    document.getElementById('host').appendChild(f);
    await new Promise(r => setTimeout(r, 0));
    f.remove();
    """,
    # Canvas readback is noised per-context by Camoufox. If the noise or its
    # seed is cached against something unbounded, this is where it shows.
    "canvas": """
    const c = document.createElement('canvas');
    c.width = 64; c.height = 64;
    const g = c.getContext('2d');
    g.fillStyle = 'rgb(' + (i % 255) + ',80,120)';
    g.fillRect(0, 0, 64, 64);
    g.fillText('churn' + i, 2, 20);
    c.toDataURL();
    """,
    # A WebGL context per iteration, each of which Camoufox answers with spoofed
    # parameters and a noised readback.
    "webgl": """
    const c = document.createElement('canvas');
    c.width = 32; c.height = 32;
    const gl = c.getContext('webgl');
    if (gl) {
      gl.clearColor((i % 100) / 100, 0.2, 0.3, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.getParameter(gl.VENDOR);
      gl.getParameter(gl.RENDERER);
      const ext = gl.getExtension('WEBGL_lose_context');
      if (ext) ext.loseContext();
    }
    """,
    # Workers get their own global, and Camoufox spoofs inside them too.
    "worker": """
    const src = 'self.onmessage = () => self.postMessage(1);';
    const url = URL.createObjectURL(new Blob([src], {type: 'text/javascript'}));
    const w = new Worker(url);
    await new Promise(r => { w.onmessage = r; w.postMessage(0); });
    w.terminate();
    URL.revokeObjectURL(url);
    """,
    # Fresh script compilation, which is what #762's asm.js creative does.
    "script": """
    const s = document.createElement('script');
    s.textContent = 'window.__v' + i + ' = (function(){ return ' + i + '; })(); delete window.__v' + i + ';';
    document.head.appendChild(s);
    s.remove();
    """,
    # Font measurement, which routes through Camoufox's font-list and spacing
    # spoofing on every fresh family name.
    "font": """
    const c = document.createElement('canvas').getContext('2d');
    c.font = (10 + (i % 30)) + 'px "NoSuchFace' + i + '", sans-serif';
    c.measureText('the quick brown fox');
    """,
}


class ChurnServer:
    """Serves the churn pages on loopback for the lifetime of a test."""

    def __init__(self, default_n: int = 200) -> None:
        self.default_n = default_n
        pages = {
            name: _PAGE.format(name=name, body=body, default_n=default_n)
            for name, body in BODIES.items()
        }

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                name = self.path.lstrip("/").split("?", 1)[0] or "iframe"
                page = pages.get(name)
                if page is None:
                    self.send_error(404)
                    return
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                # No caching, so every navigation is a real parse and compile.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args) -> None:
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "ChurnServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def url(self, name: str, n: int) -> str:
        return f"http://127.0.0.1:{self.port}/{name}?n={n}"
