"""
Local HTTP server that serves the test page and checks bundle to the browser.
"""

import http.server
import socketserver
import threading
from pathlib import Path


def start_http_server(scripts_dir: Path) -> int:
    template_path = scripts_dir / "test_page_template.html"
    bundle_path = scripts_dir / "checks-bundle.js"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Suppress access logs

        def do_GET(self):
            if self.path in ("/test", "/test/"):
                self._serve(template_path, "text/html; charset=utf-8")
            elif self.path == "/checks-bundle.js":
                self._serve(bundle_path, "application/javascript")
            else:
                self.send_response(404)
                self.end_headers()

        def _serve(self, path: Path, content_type: str):
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port
