"""What a context is, versus what a browser launch is.

Camoufox offers two ways to get an identity, and conflating them is easy:

  a **browser** launch carries one fingerprint for its whole process, resolved
  before launch and passed through CAMOU_CONFIG;

  a **context** carries the browser's fingerprint *unless* one is injected into
  it -- `AsyncNewContext()`, or `generate_context_fingerprint()` plus
  `new_context(**context_options)` and `add_init_script(init_script)`, which is
  what build-tester and tests/patches/helpers.py do.

Both halves are contracts worth pinning, and they pull in opposite directions:

  * a plain `new_context()` MUST inherit. Two tabs of the same machine that
    disagreed would be a leak, not a feature.
  * an injected context MUST get its own, and MUST NOT leak into its siblings.
    That is what the per-context patches exist for, and it is the half that
    degrades silently: a value that is really process-global looks correct in
    any single-context test and only shows up when a second context opens. It
    has happened here -- commit d17c887, "fix screen size leak in contexts".

The first draft of this file asserted that two *plain* contexts get different
fingerprints. They do not, by design, and the test failed against a real binary
the first time it ran. Pinning the contract Camoufox actually offers, rather
than the one that sounded right, is the whole point.

These assert isolation and consistency, never specific values: presets are drawn
at random, so pinning a number would make the suite a liability.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

# Read-only probes. `page.evaluate` in Camoufox reads values; it does not run
# script in the page's world, which is the whole point of the fork.
PROBES = {
    "userAgent": "navigator.userAgent",
    "platform": "navigator.platform",
    "screenWidth": "screen.width",
    "screenHeight": "screen.height",
    "hardwareConcurrency": "navigator.hardwareConcurrency",
    "timezone": "Intl.DateTimeFormat().resolvedOptions().timeZone",
    "language": "navigator.language",
}


async def probe(page) -> dict:
    out = {}
    for name, expression in PROBES.items():
        try:
            out[name] = await page.evaluate(expression)
        except Exception as exc:  # noqa: BLE001
            out[name] = f"<error: {exc}>"
    return out


async def open_page(browser, context=None):
    """A context (inheriting, unless one is given) with one page on about:blank."""
    context = context or await browser.new_context()
    page = await context.new_page()
    await page.goto("about:blank")
    return context, page


# About half of get_random_preset()'s draws produce a WebGL vendor/renderer
# combination that is not in the sample data, and AsyncNewContext raises. That is
# expected -- tests/patches/helpers.py retries the same way -- so retry rather
# than letting a draw decide whether the suite passes.
MAX_PRESET_ATTEMPTS = 15


async def injected_context(browser, **kwargs):
    """A context with its own fingerprint, retrying past unusable draws."""
    from camoufox.async_api import AsyncNewContext

    last = None
    for _ in range(MAX_PRESET_ATTEMPTS):
        try:
            return await AsyncNewContext(browser, **kwargs)
        except ValueError as exc:
            if "WebGL" not in str(exc):
                raise
            last = exc
    raise AssertionError(f"no usable preset in {MAX_PRESET_ATTEMPTS} draws: {last}")


# ---------------------------------------------------------------------------


async def test_plain_contexts_inherit_the_browser_fingerprint(binary):
    """A context is not automatically a new machine.

    Without an injected fingerprint a context belongs to the browser's identity,
    and two of them must agree. Two tabs of one machine that disagreed would be
    the leak, not the feature.
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as browser:
        ctx_a, page_a = await open_page(browser)
        ctx_b, page_b = await open_page(browser)
        a, b = await probe(page_a), await probe(page_b)
        await ctx_a.close()
        await ctx_b.close()

    differing = {k: (a.get(k), b.get(k)) for k in PROBES if a.get(k) != b.get(k)}
    assert not differing, (
        "two plain contexts in one browser reported different fingerprints: "
        f"{differing}. A context inherits the browser's identity unless one is "
        "injected into it."
    )


async def test_injected_contexts_each_get_their_own_fingerprint(binary):
    """The core promise of per-context spoofing.

    If these come back identical, per-context injection has degraded to
    process-global -- which passes every single-context test there is.
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as browser:
        ctx_a = await injected_context(browser, os="macos")
        ctx_b = await injected_context(browser, os="linux")
        _, page_a = await open_page(browser, ctx_a)
        _, page_b = await open_page(browser, ctx_b)
        a, b = await probe(page_a), await probe(page_b)
        await ctx_a.close()
        await ctx_b.close()

    differing = [k for k in PROBES if a.get(k) != b.get(k)]
    assert differing, (
        "two injected contexts reported an identical fingerprint on every probe.\n"
        f"  {a}\n"
        "Per-context injection has degraded to process-global (cf. commit d17c887)."
    )


async def test_an_injected_context_does_not_leak_into_a_plain_one(binary):
    """The d17c887 shape: injecting into one context must not move another.

    A per-context value implemented as a process-global would change the
    browser's identity for everyone the moment the first context set it.
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as browser:
        plain_ctx, plain_page = await open_page(browser)
        before = await probe(plain_page)

        injected = await injected_context(browser, os="macos")
        _, injected_page = await open_page(browser, injected)
        await probe(injected_page)

        after = await probe(plain_page)
        await injected.close()
        await plain_ctx.close()

    moved = {k: (before.get(k), after.get(k)) for k in PROBES if before.get(k) != after.get(k)}
    assert not moved, (
        f"opening an injected context changed an existing context's fingerprint: {moved}. "
        "That is a per-context value implemented as a process-global."
    )


async def test_a_context_is_internally_coherent(binary):
    """A fingerprint has to agree with itself.

    Cross-signal inconsistency -- a macOS platform with a Linux user agent -- is
    more detectable than any single wrong value, because it cannot happen on a
    real machine.
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True, os="macos",
                             i_know_what_im_doing=True) as browser:
        context, page = await open_page(browser)
        values = await probe(page)
        await context.close()

    ua = str(values.get("userAgent", ""))
    platform = str(values.get("platform", ""))
    assert "Firefox" in ua, f"user agent does not claim Firefox: {ua!r}"
    if platform.startswith("Mac"):
        assert "Macintosh" in ua, f"platform {platform!r} disagrees with user agent {ua!r}"
    assert int(values.get("screenWidth") or 0) > 1, values
    assert int(values.get("screenHeight") or 0) > 1, (
        f"screen height is {values.get('screenHeight')!r}. A 1x1 virtual display root "
        "must never clamp the generated screen -- see the `not virtual_display` guards "
        "in pythonlib/camoufox/utils.py."
    )


async def test_closing_one_context_does_not_disturb_another(binary):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as browser:
        ctx_a, page_a = await open_page(browser)
        ctx_b, page_b = await open_page(browser)
        before = await probe(page_b)
        await ctx_a.close()
        after = await probe(page_b)
        await ctx_b.close()

    assert before == after, (
        "closing one context changed another context's fingerprint:\n"
        f"  before {before}\n  after  {after}"
    )


async def test_two_browsers_get_different_fingerprints(binary):
    from camoufox.async_api import AsyncCamoufox

    async def one() -> dict:
        async with AsyncCamoufox(executable_path=str(binary), headless=True,
                                 i_know_what_im_doing=True) as browser:
            context, page = await open_page(browser)
            values = await probe(page)
            await context.close()
            return values

    a, b = await asyncio.gather(one(), one())
    differing = [k for k in PROBES if a.get(k) != b.get(k)]
    assert differing, f"two separate browser launches produced an identical fingerprint: {a}"


async def test_a_context_survives_its_sibling_browser(binary):
    """Two browsers are two processes; one closing must not affect the other."""
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as keeper:
        ctx_keep, page_keep = await open_page(keeper)
        before = await probe(page_keep)

        async with AsyncCamoufox(executable_path=str(binary), headless=True,
                                 i_know_what_im_doing=True) as transient:
            ctx_t, page_t = await open_page(transient)
            await probe(page_t)
            await ctx_t.close()

        after = await probe(page_keep)
        await ctx_keep.close()

    assert before == after, "closing a second browser perturbed the first one's fingerprint"


async def test_pages_in_one_context_share_its_fingerprint(binary):
    """A context is the isolation boundary; a page is not.

    Two pages in one context must agree, or the boundary has been drawn in the
    wrong place and a site could tell two of its own tabs apart.
    """
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(executable_path=str(binary), headless=True,
                             i_know_what_im_doing=True) as browser:
        context = await browser.new_context()
        page_one = await context.new_page()
        await page_one.goto("about:blank")
        page_two = await context.new_page()
        await page_two.goto("about:blank")
        one, two = await probe(page_one), await probe(page_two)
        await context.close()

    assert one == two, (
        "two pages in the SAME context reported different fingerprints:\n"
        f"  page 1 {one}\n  page 2 {two}"
    )
