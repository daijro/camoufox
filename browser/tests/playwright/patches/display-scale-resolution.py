"""
The (resolution) media query matches the identity's devicePixelRatio (#933).

The browser rendered at 1 while devicePixelRatio claimed the identity's display
scale, so a 250% Windows identity read (resolution: 1dppx), which no real
machine reports. The launcher now renders at the claimed scale.

    python browser/tests/playwright/patches/display-scale-resolution.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

CONFIG = {"screen.width": 1382, "screen.height": 864, "screen.availWidth": 1382, "screen.availHeight": 816,
          "window.devicePixelRatio": 2.5, "window.outerWidth": 1280, "window.outerHeight": 900,
          "window.innerWidth": 1267, "window.innerHeight": 809}
READ = "() => [devicePixelRatio, matchMedia(`(resolution: ${devicePixelRatio}dppx)`).matches]"


def main() -> int:
    from camoufox.sync_api import Camoufox

    with Camoufox(**launch_kwargs(os="windows", config=CONFIG, i_know_what_im_doing=True)) as browser:
        page = browser.new_page()
        page.set_content("<p>x</p>")
        dpr, matches = page.evaluate(READ)
    print(f"  devicePixelRatio {dpr}, (resolution: {dpr}dppx) {matches}")
    if dpr != 2.5 or not matches:
        print("FAIL: (resolution) does not match devicePixelRatio 2.5")
        return 1
    print("PASS: (resolution) matches devicePixelRatio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
