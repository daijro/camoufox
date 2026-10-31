"""
The (resolution) media query matches the identity's devicePixelRatio (#933).

The browser rendered at 1 while devicePixelRatio claimed the identity's display
scale, so a 250% Windows identity read (resolution: 1dppx), which no real
machine reports. The launcher now renders at the claimed scale. That includes
a ratio of 1 on a HiDPI host, which otherwise rendered at the host's scale and
read (resolution: 2dppx). The host is a private Xvfb display with GDK_SCALE=2.

    python browser/tests/playwright/patches/display-scale-resolution.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, launch_kwargs  # noqa: E402

SCREEN = {"screen.width": 1382, "screen.height": 864, "screen.availWidth": 1382, "screen.availHeight": 816,
          "window.outerWidth": 1280, "window.outerHeight": 900,
          "window.innerWidth": 1267, "window.innerHeight": 809}
READ = "() => [devicePixelRatio, matchMedia(`(resolution: ${devicePixelRatio}dppx)`).matches]"


def read(dpr: float, **kwargs) -> list:
    from camoufox.sync_api import Camoufox

    config = {**SCREEN, "window.devicePixelRatio": dpr}
    with Camoufox(**launch_kwargs(os="windows", config=config, i_know_what_im_doing=True, **kwargs)) as browser:
        page = browser.new_page()
        page.set_content("<p>x</p>")
        return page.evaluate(READ)


def read_on_hidpi_host(dpr: float) -> list:
    with hidden_display("2800x1800"):
        os.environ["GDK_SCALE"] = "2"
        return read(dpr, headless=False)


def main() -> int:
    failures = []
    for label, dpr, (seen, matches) in (("headless", 2.5, read(2.5)),
                                        ("headed on a 2x host", 1, read_on_hidpi_host(1))):
        print(f"  {label}: devicePixelRatio {seen}, (resolution: {seen}dppx) {matches}")
        if seen != dpr or not matches:
            failures.append(f"{label}: (resolution) does not match devicePixelRatio {dpr}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: (resolution) matches devicePixelRatio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
