"""Serve page.html, launch a Firefox at it, print what the page POSTs as JSON.

  python3 -I probe.py <firefox binary> [pref=value ...]

Headless, a fresh profile, up to 240 s.
"""
import http.server, json, os, shutil, subprocess, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
TYPES = {".html": "text/html", ".woff": "font/woff", ".ttf": "font/ttf", ".b64": "text/plain"}
result = {}
done = threading.Event()

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        name = os.path.basename(self.path.split("?")[0]) or "page.html"
        path = os.path.join(HERE, name)
        if not os.path.isfile(path):
            self.send_response(404); self.end_headers(); return
        body = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(os.path.splitext(name)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        result.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204); self.end_headers(); done.set()

srv = http.server.HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
prof = tempfile.mkdtemp(prefix="archprobe-")
with open(os.path.join(prof, "user.js"), "w") as f:
    f.write('user_pref("browser.shell.checkDefaultBrowser", false);\n')
    for kv in sys.argv[2:]:
        k, v = kv.split("=", 1); f.write(f'user_pref("{k}", {v});\n')
ff = subprocess.Popen([sys.argv[1], "-headless", "-no-remote", "-profile", prof, f"http://127.0.0.1:{srv.server_port}/page.html"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
ok = done.wait(240)
ff.kill(); ff.wait()
shutil.rmtree(prof, ignore_errors=True)
print(json.dumps(result if ok else {"error": "timeout"}, sort_keys=True))
