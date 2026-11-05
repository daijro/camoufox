r"""
A context's identity holds on a page's initial about:blank, as on a served page.

Juggler ran a context's init scripts on documents it saw created; a new page's
initial about:blank was created before Juggler's FrameTree, so it never ran
them. A driver that called set_content() on a fresh page, without navigating,
read the launch identity -- navigator.platform and appVersion of the launch OS
-- next to the context's own user agent. Now Juggler runs the context's init
scripts on that document too.

The launch identity is Windows; contexts claim macOS and Linux, and each has
a timezone and locale the launch does not, and an init script of the test's
own that marks the document. On the initial about:blank (set_content(), no
navigation) the marker, the navigator, the timezone and the language must
equal what a served page in the same context reads.

    python browser/tests/playwright/patches/juggler-initial-blank-context.py
"""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

READ = """() => ({
  marker: window.name,
  platform: navigator.platform, appVersion: navigator.appVersion, userAgent: navigator.userAgent,
  oscpu: navigator.oscpu, hardwareConcurrency: navigator.hardwareConcurrency,
  language: navigator.language, timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  offset: new Date(2026, 0, 1).getTimezoneOffset(),
})"""

# Another OS than the launch's, and per-user values no launch default carries.
CONTEXTS = (
    {"os": "macos", "timezone_id": "Asia/Tokyo", "locale": "de-DE"},
    {"os": "linux", "timezone_id": "America/Sao_Paulo", "locale": "pt-BR"},
)


class _Page(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<!doctype html><body><p>x</p></body>")


def main() -> int:
    from camoufox.sync_api import Camoufox, NewContext

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    failures = []
    with Camoufox(**launch_kwargs(os="windows", canvas_noise=True, i_know_what_im_doing=True)) as browser:
        for kwargs in CONTEXTS:
            name = kwargs["timezone_id"]
            context = NewContext(browser, **kwargs)
            # window.name: a DOM property, so the evaluating world reads what
            # the page's world set.
            context.add_init_script(f"window.name = {name!r};")
            blank_page = context.new_page()
            blank_page.set_content("<p>x</p>")
            blank = blank_page.evaluate(READ)
            blank_url = blank_page.url
            served_page = context.new_page()
            served_page.goto(url)
            served = served_page.evaluate(READ)
            context.close()
            print(f"  {kwargs['os']:6s} {name:18s} set_content on {blank_url}: {blank}")
            print(f"  {kwargs['os']:6s} {name:18s} served page:            {served}")
            if served["marker"] != name or served["timeZone"] != name:
                failures.append(f"{name}: the served page did not get the context's own values: {served}")
            for key, value in served.items():
                if blank[key] != value:
                    failures.append(f"{kwargs['os']} {name}: initial about:blank {key} {blank[key]!r}, "
                                    f"the context's is {value!r}")
    server.shutdown()
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: set_content() on a fresh page reads the context's identity, as a served page does.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
