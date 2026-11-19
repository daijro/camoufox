r"""
A Windows identity's CSS2 system-font keywords are 12px at every display scale.

Stock Windows Firefox converts the NONCLIENTMETRICS font height to CSS px, so
`font: caption` (and icon, menu, message-box, small-caption, status-bar)
computes to 12px whatever devicePixelRatio is. font-system-fonts-css2.patch
multiplied 12 by the claimed devicePixelRatio: 30px at dpr 2.5, where stock
Windows Firefox says 12px.

    python browser/tests/playwright/patches/system-font-size-windows.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """() => ['caption', 'icon', 'menu', 'message-box', 'small-caption', 'status-bar'].map((k) => {
  const el = document.createElement('div');
  el.style.font = k;
  document.body.appendChild(el);
  const size = getComputedStyle(el).fontSize;
  el.remove();
  return size;
})"""


async def probe(binary, dpr):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, os="windows", executable_path=str(binary),
                             config={"window.devicePixelRatio": dpr}, i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.set_content("<body></body>")
        return await page.evaluate(PROBE)


def main():
    binary = resolve_binary()
    failures = []
    for dpr in (1.0, 1.25, 2.5):
        sizes = asyncio.run(probe(binary, dpr))
        print(f"dpr {dpr}: {sizes}")
        if any(s != "12px" for s in sizes):
            failures.append(f"dpr {dpr}: {sizes}, stock 12px")
    for f in failures:
        print("FAIL", f)
    print("FAIL" if failures else "PASS")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
