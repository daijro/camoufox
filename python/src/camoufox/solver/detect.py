"""Detect whether a Playwright page is a Cloudflare challenge or Turnstile widget.

The markers below are Cloudflare's own, read from the challenge page the cfsolve
captures were taken against. Detection is deliberately shallow — one title
check promising the interstitial, one DOM check for the script that builds the
widget — so a page that merely *mentions* Cloudflare in prose is not mistaken for
one that is serving a challenge.
"""

from __future__ import annotations

__all__ = [
    "CF_TITLE_MARKERS",
    "SITEWAIT_SELECTOR",
    "TURNSTILE_SELECTOR",
    "is_cloudflare_challenge",
    "is_cloudflare_challenge_async",
    "extract_sitekey",
    "extract_sitekey_async",
]

# Titles of the served interstitial ("Just a moment...") and of the managed
# challenge modal ("Attention Required!"). Lower-cased for the title test.
CF_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
)

# The orchestrator script the interstitial injects, and the widget container a
# Turnstile challenge renders. Either being present means a challenge is on screen.
SITEWAIT_SELECTOR = "script[src*='/_cf_chl_']"
TURNSTILE_SELECTOR = ".cf-turnstile, div#cf-challenge-running"


def _title_is_challenge(title) -> bool:
    """Cloudflare's interstitial titles, ignoring trailing punctuation.

    The served pages are "Just a moment...", "Attention Required!" and
    "Checking your browser before accessing ...", so an exact match against the
    markers would miss every one of them.
    """
    normalised = (title or "").strip().lower()
    for marker in CF_TITLE_MARKERS:
        if normalised.startswith(marker):
            return True
    return False


def is_cloudflare_challenge(page) -> bool:
    """Synchronous (sync_api.Page) check."""
    if _title_is_challenge(page.title()):
        return True
    return bool(page.query_selector(SITEWAIT_SELECTOR) or page.query_selector(TURNSTILE_SELECTOR))


async def is_cloudflare_challenge_async(page) -> bool:
    """async_api.Page/Page-alike check."""
    if _title_is_challenge(await page.title()):
        return True
    return bool(
        await page.query_selector(SITEWAIT_SELECTOR) or await page.query_selector(TURNSTILE_SELECTOR)
    )


_SITEKEY_JS = (
    "() => { const el = document.querySelector('.cf-turnstile, [data-sitekey]');"
    " return el ? el.getAttribute('data-sitekey') : null; }"
)


def extract_sitekey(page) -> str | None:
    """The sitekey of the page's first .cf-turnstile/[data-sitekey] container."""
    try:
        return page.evaluate(_SITEKEY_JS) or None
    except Exception:
        return None


async def extract_sitekey_async(page) -> str | None:
    try:
        return (await page.evaluate(_SITEKEY_JS)) or None
    except Exception:
        return None
