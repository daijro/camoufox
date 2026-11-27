"""
With proxies on contexts only, the browser's own traffic goes through one too.

A launch can leave the browser without a proxy and give each context its own
(new_context(proxy=...)), one identity per context. The browser's own
connections belong to no context: the push websocket every context shares,
media plugin update checks. Juggler gave them no proxy, so they went out
direct from this machine's address (5 direct connections in 120 s, measured
2026-11-09), while every page went through its proxy. Playwright's rule (a
context's proxy, else the launch proxy) leaves them none. They now take the
first proxied context's proxy, for the browser's life
(TargetRegistry.getProxyInfo), so it does not move as contexts open and close.

The push server is pointed at a host only a proxy can see, so the check needs
no network: a page in a proxied context subscribes, and the push connection
must reach a logging proxy. It runs once with an open proxy and once with one
that demands credentials: a request no page owns still has to answer the
proxy's 407 with the context's username and password. A third run opens two
proxied contexts and closes the first before the second subscribes.

What PASS means:
    * the proxy works: the proxied context's navigation reaches it;
    * the subscription's push connection, which no page owns, reaches it too;
    * with two contexts, it reaches the first context's proxy, closed or not,
      and never the second's.

    python browser/tests/playwright/patches/context-proxy-browser-traffic.py
"""

import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import PushSite, RefusingProxy, resolve_binary, subscribe_to_push, wait_for_push  # noqa: E402

CONTROL_HOST = "control.camoufox.test"
PUSH_HOST = "push.camoufox.test"
SUBSCRIBE_SECONDS = 30
CREDENTIALS = ("camoufox", "secret")


def launch():
    from camoufox.sync_api import Camoufox

    return Camoufox(
        headless=True,
        os="linux",
        executable_path=str(resolve_binary()),
        i_know_what_im_doing=True,
        firefox_user_prefs={"dom.push.serverURL": f"wss://{PUSH_HOST}/"},
    )


def settings_for(proxy: RefusingProxy, credentials: Optional[Tuple[str, str]]) -> dict:
    settings = {"server": f"http://127.0.0.1:{proxy.server_address[1]}"}
    if credentials:
        settings.update(username=credentials[0], password=credentials[1])
    return settings


def pushed(proxy: RefusingProxy) -> List[str]:
    return [seen for seen in proxy.seen if PUSH_HOST in seen]


def push_from(context, site: PushSite, proxies: List[RefusingProxy]) -> None:
    """Subscribe from a page in context; wait until the push connection reaches one of proxies."""
    context.grant_permissions(["notifications"])
    page = context.new_page()
    # localhost is never proxied, so the page itself loads direct; only the
    # push connection it causes is the browser's own. It goes before any
    # proxied page request: once a page has answered the proxy's 407,
    # Firefox's auth cache would answer it for the push connection too.
    page.goto(site.url)
    wait_for_push(page)
    subscribe_to_push(page)
    deadline = time.monotonic() + SUBSCRIBE_SECONDS
    while time.monotonic() < deadline and not any(pushed(proxy) for proxy in proxies):
        time.sleep(0.2)


def report(title: str, checks) -> bool:
    print(title)
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return passed


def run(site: PushSite, credentials: Optional[Tuple[str, str]]) -> bool:
    proxy = RefusingProxy(credentials)
    with launch() as browser:
        context = browser.new_context(proxy=settings_for(proxy, credentials))
        push_from(context, site, [proxy])
        try:
            context.new_page().goto(f"http://{CONTROL_HOST}/", timeout=10_000)
        except Exception:
            pass
    control = [seen for seen in proxy.seen if CONTROL_HOST in seen]
    return report("with credentials:" if credentials else "open proxy:", [
        ("the context's navigation reaches its proxy", bool(control), control),
        ("the push connection reaches it too", bool(pushed(proxy)), pushed(proxy)),
    ])


def run_two(site: PushSite) -> bool:
    first, second = RefusingProxy(CREDENTIALS), RefusingProxy()
    with launch() as browser:
        first_context = browser.new_context(proxy=settings_for(first, CREDENTIALS))
        second_context = browser.new_context(proxy=settings_for(second, None))
        first_context.close()
        push_from(second_context, site, [first, second])
    return report("two contexts, the first closed:", [
        ("the push connection reaches the first context's proxy", bool(pushed(first)), pushed(first)),
        ("and never the second's", not pushed(second), pushed(second)),
    ])


def main() -> int:
    site = PushSite()
    results = [run(site, credentials) for credentials in (None, CREDENTIALS)]
    results.append(run_two(site))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
