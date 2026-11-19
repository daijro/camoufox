"""
CSS device-width keeps the screen's fractional CSS size, as stock's does.

At a fractional devicePixelRatio a screen's CSS size is fractional too: a
3456x2160 panel at 250 % is 1382.4x864 CSS px. screen.width rounds it to 1382,
but media queries compare against the unrounded size, so in stock Firefox
`(device-width: 1382px)` and `(device-aspect-ratio: 1382/864)` are false.
Camoufox answered them from screen.width, so both were true
(screen-spoofing.patch, GetDeviceSize).

The guard runs on a hidden 3456x2160 display at the identity's 2.5: the
rounded size must not match, the real one must. The control is a display that
is not the identity's screen (3840x2400, 1536x960 CSS px), where the claimed size is all there
is and the rounded query matches.

    python browser/tests/playwright/patches/css-device-size-fractional.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

CONFIG = {"window.devicePixelRatio": 2.5, "screen.width": 1382, "screen.height": 864,
          "screen.availWidth": 1382, "screen.availHeight": 816, "window.outerWidth": 1280,
          "window.outerHeight": 816}
PROBE = """() => ({
  width: screen.width,
  rounded: matchMedia('(device-width: 1382px)').matches,
  aspect: matchMedia('(device-aspect-ratio: 1382/864)').matches,
  real: matchMedia('(min-device-width: 1382.3px) and (max-device-width: 1382.5px)').matches,
})"""


def probe(binary, display):
    from camoufox.sync_api import Camoufox

    with hidden_display(display):
        with Camoufox(executable_path=str(binary), headless=False, os="windows", config=CONFIG,
                      i_know_what_im_doing=True) as browser:
            page = browser.new_page()
            page.set_content("<body></body>")
            return page.evaluate(PROBE)


def main() -> int:
    binary = resolve_binary()
    failures = []
    real = probe(binary, "3456x2160")
    other = probe(binary, "3840x2400")
    print(f"  3456x2160 {real}\n  3840x2400 {other}")
    if real["width"] != 1382:
        failures.append(f"screen.width is {real['width']}, not the identity's 1382")
    if real["rounded"] or real["aspect"] or not real["real"]:
        failures.append("on the identity's own screen, device-width is the rounded 1382, stock's is 1382.4")
    if not other["rounded"] or not other["aspect"]:
        failures.append("on another display, device-width is not the claimed 1382x864")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: device-width is the real screen's fractional size when it is the identity's, the claimed size otherwise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
