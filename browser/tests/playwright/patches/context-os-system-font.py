r"""
A context's system fonts follow the OS that context presents.

`system-ui` and the CSS2 system-font keywords (`font: caption` and the rest)
resolve to the claimed OS's interface font (system-ui-font-spoofing.patch,
font-system-fonts-css2.patch). They asked the launch's navigator.platform, once
for the whole browser, so a context drawn for another OS -- possible on a
browser launched with canvas_noise=True -- reported its own navigator.platform
next to the launch OS's interface font:

    AsyncNewContext(browser, os="macos") on a browser launched os="windows":
    navigator.platform "MacIntel", getComputedStyle(caption).fontFamily "Segoe UI"

Each context here is probed for its platform, the family `font: caption`
computes to, and whether `system-ui` measures as that OS's interface family.

    python browser/tests/playwright/patches/context-os-system-font.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# navigator.platform -> (the family `font: caption` computes to, the family
# system-ui resolves to), as the patches spoof them.
EXPECTED = {
    "Win32": ("Segoe UI", "Segoe UI"),
    "MacIntel": ("-apple-system", "Helvetica"),
}

PROBE = """(uiFamily) => {
  const el = document.createElement('div');
  el.style.font = 'caption';
  document.body.appendChild(el);
  const caption = getComputedStyle(el).fontFamily;
  el.remove();
  const ctx = document.createElement('canvas').getContext('2d');
  const width = font => { ctx.font = font; return ctx.measureText('mmmmmmmmmmlli10OQ@#').width; };
  return {
    platform: navigator.platform,
    caption,
    systemUiIsUiFamily: width('40px system-ui') === width(`40px "${uiFamily}", monospace`),
    uiFamilyInstalled: width(`40px "${uiFamily}", monospace`) !== width('40px monospace'),
  };
}"""


async def run(binary):
    from camoufox.async_api import AsyncCamoufox, AsyncNewContext

    results = []
    async with AsyncCamoufox(headless=True, os="windows", canvas_noise=True,
                             executable_path=str(binary), i_know_what_im_doing=True) as browser:
        launch_page = await browser.new_page()
        await launch_page.set_content("<body></body>")
        results.append(await launch_page.evaluate(PROBE, EXPECTED["Win32"][1]))

        context = await AsyncNewContext(browser, os="macos")
        page = await context.new_page()
        await page.set_content("<body></body>")
        results.append(await page.evaluate(PROBE, EXPECTED["MacIntel"][1]))
    return results


def main() -> int:
    results = asyncio.run(run(resolve_binary()))
    failures = []
    for got in results:
        print(got)
        if got["platform"] not in EXPECTED:
            failures.append(f"unexpected navigator.platform {got['platform']!r}")
            continue
        caption, ui_family = EXPECTED[got["platform"]]
        if got["caption"] != caption:
            failures.append(f"{got['platform']}: font: caption computes to {got['caption']!r}, "
                            f"expected {caption!r}")
        if not got["uiFamilyInstalled"]:
            failures.append(f"{got['platform']}: {ui_family} is not available, so system-ui cannot be checked")
        elif not got["systemUiIsUiFamily"]:
            failures.append(f"{got['platform']}: system-ui does not resolve to {ui_family}")
    if [got["platform"] for got in results] != ["Win32", "MacIntel"]:
        failures.append("the launch and the context did not claim Windows and macOS")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: each context's system fonts follow its own OS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
