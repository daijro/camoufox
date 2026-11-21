"""Automatic Cloudflare/Turnstile solving for Camoufox pages, backed by cfsolve.

Two levels, both opt-in:

* :func:`solve_page` — solve once, on a page that is already showing a challenge.
* :func:`install` — attach to a browser or context so every page it opens is
  solved after navigation, whenever a challenge is served.

`cfsolve` runs out of process (see ``bridge.py``); this module only decides
*when* to call it and what to do with the answer. A returned token belongs to a
Turnstile widget and is handed to that widget's response field; a returned
``cf_clearance`` is a cookie, so it is written into the context and the page is
allowed to continue.

Solving is best-effort by default: a site with no challenge, a missing binary,
or a solve that produces nothing must not break the caller's navigation. Pass
``strict=True`` to turn those failures into exceptions.
"""

from __future__ import annotations

import functools

from urllib.parse import urlsplit

from .bridge import CFSolveBridge, CFSolveError
from .detect import extract_sitekey, is_cloudflare_challenge

__all__ = ["solve_page", "install", "AutoSolveError", "CF_CLEARANCE", "RESPONSE_FIELD"]

CF_CLEARANCE = "cf_clearance"
RESPONSE_FIELD = "cf-turnstile-response"

# Common two-label public suffixes. A cookie must never be scoped to one of
# these (`.co.uk` would leak the cookie across every registrant), and there is no
# PSL in the standard library, so the ones that show up in practice are listed.
_PUBLIC_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "sch.uk",
        "com.au", "net.au", "org.au", "edu.au", "gov.au",
        "co.in", "net.in", "org.in", "gen.in", "firm.in",
        "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
        "co.nz", "net.nz", "org.nz", "govt.nz",
        "co.za", "org.za", "com.br", "com.mx", "com.tr", "com.cn",
        "com.sg", "com.hk", "com.tw", "co.kr", "co.il", "com.ar",
    }
)

# Paste a solved token into the widget the page is showing. Turnstile keeps the
# token in a hidden textarea named `cf-turnstile-response`, and calls the
# widget's `callback` with it; both are done, because a site may read either.
_INJECT_TOKEN_JS = """
(responseName, token) => {
  let found = false;
  for (const el of document.querySelectorAll('[name="' + responseName + '"]')) {
    el.value = token;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    found = true;
  }
  const containers = document.querySelectorAll('.cf-turnstile, [data-sitekey]');
  for (const box of containers) {
    const id = box.getAttribute('data-callback') || box.getAttribute('callback');
    if (id && typeof window[id] === 'function') {
      try { window[id](token); found = true; } catch (e) {}
    }
  }
  if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
    found = true;  // the widget exists; a form submit will now carry the token
  }
  return found;
}
"""


class AutoSolveError(CFSolveError):
    """A solve was attempted and did not produce a usable answer."""


def _clearance_domain(url):
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        raise AutoSolveError(f"cannot scope a cookie to an unusable URL: {url!r}")
    return host


def _cookie_domains(host):
    """Where cf_clearance may legitimately be set, most specific first.

    The exact host always works. Cloudflare itself sets the cookie on the
    registrable domain so subdomains inherit it; that is the first parent which
    is not itself a public suffix.
    """
    domains = [host, "." + host]
    labels = host.split(".")
    for index in range(1, len(labels) - 1):
        parent = ".".join(labels[index:])
        if parent in _PUBLIC_SUFFIXES:
            break
        domains.append("." + parent)
    return domains


def _set_clearance(page, value, url):
    """Write `cf_clearance` for the page's host into its context."""
    domain = _clearance_domain(url)

    context = page.context
    for candidate in _cookie_domains(domain):
        try:
            context.add_cookies(
                [
                    {
                        "name": CF_CLEARANCE,
                        "value": value,
                        "domain": candidate,
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None",
                    }
                ]
            )
            return candidate
        except Exception:
            continue
    raise AutoSolveError(f"could not set {CF_CLEARANCE} for {domain}")


def solve_page(
    page,
    bridge: CFSolveBridge,
    *,
    sitekey=None,
    action=None,
    cdata=None,
    reload_after_clearance=True,
    timeout=180.0,
    strict=False,
):
    """Solve the challenge `page` is showing, if any.

    Returns the :class:`~camoufox.solver.bridge.SolveResult` on success, or
    ``None`` when there was no challenge to solve. With ``strict=False`` (the
    default) a failed attempt also returns ``None`` instead of raising.
    """
    url = page.url
    try:
        if not is_cloudflare_challenge(page):
            return None

        sitekey = sitekey or extract_sitekey(page)
        result = bridge.solve(url, sitekey=sitekey, action=action, cdata=cdata)

        if result.kind == "clearance":
            _set_clearance(page, result.value, url)
            if reload_after_clearance:
                # The clearance is a cookie; the page has to be re-requested for
                # the site to see it. domcontentloaded is enough to hand control
                # back, and a navigation already in flight is not disturbed.
                page.wait_for_load_state("domcontentloaded")
        else:
            page.evaluate(_INJECT_TOKEN_JS, RESPONSE_FIELD, result.value)
        return result
    except Exception as exc:
        if strict:
            raise AutoSolveError(str(exc)) from exc
        return None


def _patch_sync_page(page, bridge, options, solved):
    """Wrap this page's `goto` so a challenge served by it is answered."""
    original = page.goto

    @functools.wraps(original)
    def goto(*args, **kwargs):
        response = original(*args, **kwargs)
        if id(page) in solved:
            return response
        if solve_page(page, bridge, **options) is not None:
            solved.add(id(page))
        return response

    page.goto = goto
    return page


def install(
    target,
    bridge: CFSolveBridge,
    *,
    sitekey=None,
    action=None,
    cdata=None,
    reload_after_clearance=True,
    timeout=180.0,
    strict=False,
    solve_existing=True,
):
    """Solve challenges automatically for every page `target` opens.

    `target` is a Playwright ``Browser``/``BrowserContext`` (sync API), as
    returned by ``Camoufox(...).__enter__()``. Pages already open are patched
    too, and — unless ``solve_existing=False`` — any that is sitting on a
    challenge right now is solved immediately.

    Returns `target`, so it can be used inline:

        with Camoufox(headless='virtual') as browser:
            install(browser, bridge)
            page = browser.new_page()
            page.goto('https://example.com')
    """
    options = {
        "sitekey": sitekey,
        "action": action,
        "cdata": cdata,
        "reload_after_clearance": reload_after_clearance,
        "timeout": timeout,
        "strict": strict,
    }
    solved = set()

    def prepare(page):
        if getattr(page, "_camoufox_autosolve", False):
            return page
        page._camoufox_autosolve = True
        _patch_sync_page(page, bridge, options, solved)
        if solve_existing and solve_page(page, bridge, **options) is not None:
            solved.add(id(page))
        return page

    # `BrowserContext.pages` is a property (a list); a Browser exposes pages
    # through events instead, and has no such attribute at all.
    existing_pages = getattr(target, "pages", None)
    if callable(existing_pages):
        existing_pages = existing_pages()
    for existing in existing_pages or []:
        prepare(existing)

    try:
        target.on("page", prepare)
    except Exception:
        pass

    factory = getattr(target, "new_page", None)
    if factory is not None:

        @functools.wraps(factory)
        def new_page(*args, **kwargs):
            page = factory(*args, **kwargs)
            prepare(page)
            return page

        target.new_page = new_page

    return target
