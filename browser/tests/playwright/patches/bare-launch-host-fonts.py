r"""
A launch without the launcher's config renders the host's fonts, as stock Firefox does.

Every package ships the font sets of all three OSes under fonts/, for identities
the launcher draws. A launch with no CAMOU_CONFIG claims no OS, so it is the
host's (plain Playwright on camoufox-bin, for example): its fonts must be the
host's own plus what stock Firefox bundles (Twemoji Mozilla), never the OS sets.
Before #997, Linux added fonts/ recursively (FcConfigAppFontAddDir), so a bare
launch on Linux rendered every set: Segoe UI, Lucida Console and Cambria Math
resolved beside a Linux User-Agent, which Akamai's detectOSFontsSignal reads as
Windows, and sans-serif measured 99 px high where stock measures 98.

The reference is the same binary on a profile with gfx.bundled-fonts.activate=0,
which registers nothing from fonts/. Each family the bundle can render
(python/src/camoufox/fonts.json, every OS) is measured against the generic
fallbacks, and the generics are measured as a 72 px span. Both launches must
agree, except for Twemoji Mozilla, which only the default launch has.

    python browser/tests/playwright/patches/bare-launch-host-fonts.py
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]

STOCK_BUNDLED = "Twemoji Mozilla"
ORIGIN = "https://camoufox.test/"
PAGE = r"""<!doctype html><meta charset=utf-8><body><script>
const families = %FAMILIES%;
const ctx = document.createElement('canvas').getContext('2d');
const text = 'mmmmmmmmmmlli1WQ@#';
const generics = ['serif', 'sans-serif', 'monospace'];
const width = font => { ctx.font = font; return ctx.measureText(text).width; };
const fallback = Object.fromEntries(generics.map(g => [g, width('72px ' + g)]));
const rendered = families.filter(f => generics.some(g => width(`72px "${f}", ${g}`) !== fallback[g]));
const spans = {};
for (const g of generics) {
  const span = document.createElement('span');
  span.style.cssText = `position:absolute;font-size:72px;font-family:${g}`;
  span.textContent = 'abcdefghijklmnopqrstuvwxyz0123456789';
  document.body.append(span);
  const box = span.getBoundingClientRect();
  spans[g] = [box.width, box.height];
  span.remove();
}
document.documentElement.dataset.probe = JSON.stringify({rendered, spans});
</script>"""


def bundle_families() -> List[str]:
    lists = json.loads((REPO_ROOT / "python" / "src" / "camoufox" / "fonts.json").read_text())
    return sorted(set().union(*lists.values()))


async def probe(binary: Path, bundled_fonts: bool) -> Dict[str, Any]:
    from playwright.async_api import async_playwright

    page_html = PAGE.replace("%FAMILIES%", json.dumps(bundle_families()))
    with tempfile.TemporaryDirectory() as profile:
        if not bundled_fonts:
            # The font list reads this pref once, at startup, so it goes in the
            # profile before the browser starts.
            Path(profile, "prefs.js").write_text('user_pref("gfx.bundled-fonts.activate", 0);\n')
        async with async_playwright() as p:
            context = await p.firefox.launch_persistent_context(
                profile, executable_path=str(binary), headless=True)
            try:
                page = await context.new_page()
                await page.route(ORIGIN, lambda route: route.fulfill(content_type="text/html", body=page_html))
                await page.goto(ORIGIN)
                result = await page.wait_for_function("() => document.documentElement.dataset.probe")
                return json.loads(await result.json_value())
            finally:
                await context.close()


async def main() -> int:
    binary = resolve_binary()
    print(f"Binary: {binary}")
    bare = await probe(binary, bundled_fonts=True)
    host = await probe(binary, bundled_fonts=False)
    failures: List[str] = []

    if STOCK_BUNDLED not in bare["rendered"]:
        failures.append(f"{STOCK_BUNDLED}, which stock Firefox bundles, does not render")
    if STOCK_BUNDLED in host["rendered"]:
        failures.append(f"{STOCK_BUNDLED} renders with gfx.bundled-fonts.activate=0: the reference is not the host's fonts")
    extra = sorted(set(bare["rendered"]) - set(host["rendered"]) - {STOCK_BUNDLED})
    missing = sorted(set(host["rendered"]) - set(bare["rendered"]))
    print(f"  families rendered: {len(bare['rendered'])} bare, {len(host['rendered'])} with the host's fonts only")
    if extra:
        failures.append(f"{len(extra)} bundled families render that the host does not have: {', '.join(extra[:12])}")
    if missing:
        failures.append(f"{len(missing)} host families do not render: {', '.join(missing[:12])}")
    for generic, size in bare["spans"].items():
        print(f"  {generic}: {size} bare, {host['spans'][generic]} host")
        if size != host["spans"][generic]:
            failures.append(f"{generic} measures {size}, the host's fonts {host['spans'][generic]}")

    print()
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a launch without the launcher's config renders the host's fonts and Firefox's own")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
