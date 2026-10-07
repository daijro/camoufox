"""
Verify animations run on stock timing unless `instantAnimations` is set.

no-css-animations.patch can finish every finite animation at once, so Playwright
never waits on one. That used to be the default, and a page could read it back in
one line: `el.animate(frames, 1000).effect.getComputedTiming().duration` was 0
where stock Firefox reports 1000, and a CSS transition reported 0 as well. It is
now an opt-in.

What PASS means:
    * by default, a 1000ms Web Animation and a 500ms CSS transition report
      their real durations;
    * with config {"instantAnimations": True}, both report 0.

    python browser/tests/playwright/patches/animation-timing.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """() => {
  const animation = document.body.animate([{opacity: 0}, {opacity: 1}], 1000);
  const el = document.createElement('div');
  document.body.append(el);
  el.style.transition = 'opacity 500ms';
  el.style.opacity = '0';
  el.offsetWidth;
  el.style.opacity = '1';
  return {
    animation: animation.effect.getComputedTiming().duration,
    transition: el.getAnimations().map(a => a.effect.getComputedTiming().duration),
  };
}"""


async def probe(config):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, os="linux", config=config,
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.set_content("<body></body>")
        return await page.evaluate(PROBE)


async def main() -> int:
    passed = True
    for config, expected in (({}, {"animation": 1000, "transition": [500]}),
                             ({"instantAnimations": True}, {"animation": 0, "transition": [0]})):
        label = "instantAnimations" if config else "default"
        got = await probe(dict(config))  # the launcher fills in the dict it is given
        if got == expected:
            print(f"  PASS {label}: {got}")
        else:
            passed = False
            print(f"  FAIL {label}: got {got}, expected {expected}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
