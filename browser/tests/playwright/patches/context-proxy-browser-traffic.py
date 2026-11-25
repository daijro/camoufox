"""
With proxies on contexts only, the browser's own traffic goes through one too.

A launch can leave the browser without a proxy and give each context its own
(new_context(proxy=...)), one identity per context. The browser's own
connections belong to no context: the push websocket every context shares,
media plugin update checks. Juggler gave them no proxy, so they went out
direct from this machine's address (5 direct connections in 120 s, measured
2026-11-09), while every page went through its proxy. They now take the newest
proxied context's proxy (TargetRegistry.getProxyInfo).

The push server is pointed at a host only a proxy can see, so the check needs
no network: a page in the proxied context subscribes, and the push connection
must reach the logging proxy. It runs once with an open proxy and once with one
that demands credentials: a request no page owns still has to answer the
proxy's 407 with the context's username and password.

What PASS means, with either proxy:
    * the proxy works: the proxied context's navigation reaches it;
    * the subscription's push connection, which no page owns, reaches it too.

    python browser/tests/playwright/patches/context-proxy-browser-traffic.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import PushSite, RefusingProxy, resolve_binary, subscribe_to_push, wait_for_push  # noqa: E402

CONTROL_HOST = "control.camoufox.test"
PUSH_HOST = "push.camoufox.test"
SUBSCRIBE_SECONDS = 30
CREDENTIALS = ("camoufox", "secret")


def run(site: PushSite, credentials) -> bool:
    from camoufox.sync_api import Camoufox

    proxy = RefusingProxy(credentials)
    settings = {"server": f"http://127.0.0.1:{proxy.server_address[1]}"}
    if credentials:
        settings.update(username=credentials[0], password=credentials[1])

    with Camoufox(
        headless=True,
        os="linux",
        executable_path=str(resolve_binary()),
        i_know_what_im_doing=True,
        firefox_user_prefs={"dom.push.serverURL": f"wss://{PUSH_HOST}/"},
    ) as browser:
        context = browser.new_context(proxy=settings)
        context.grant_permissions(["notifications"])
        page = context.new_page()

        # localhost is never proxied, so the page itself loads direct; only
        # the push connection it causes is the browser's own. It goes first:
        # once a page has answered the proxy's 407, Firefox's auth cache would
        # answer it for the push connection too.
        page.goto(site.url)
        wait_for_push(page)
        subscribe_to_push(page)
        deadline = time.monotonic() + SUBSCRIBE_SECONDS
        while time.monotonic() < deadline and not any(PUSH_HOST in seen for seen in proxy.seen):
            time.sleep(0.2)
        push = [seen for seen in proxy.seen if PUSH_HOST in seen]

        try:
            page.goto(f"http://{CONTROL_HOST}/", timeout=10_000)
        except Exception:
            pass
        control = [seen for seen in proxy.seen if CONTROL_HOST in seen]

    checks = [
        ("the context's navigation reaches its proxy", bool(control), control),
        ("the push connection reaches it too", bool(push), push),
    ]
    print("with credentials:" if credentials else "open proxy:")
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return passed


def main() -> int:
    site = PushSite()
    results = [run(site, credentials) for credentials in (None, CREDENTIALS)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
