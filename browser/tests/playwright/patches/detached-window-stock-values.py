"""
A window whose iframe was removed answers what stock's does, not the identity's.

A removed iframe's window has no pres context and no widget. Stock Firefox then
answers devicePixelRatio 1 and navigator.maxTouchPoints 0, whatever the screen
(measured on Windows at 250 % and on Linux). Camoufox answered the identity's
devicePixelRatio and touch points there (fingerprint-injection.patch,
zz-stock-cost-parity.patch), so a page that kept a removed frame's window read
a value no stock browser gives.

    python browser/tests/playwright/patches/detached-window-stock-values.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

# A touchscreen identity: stock's baseline fingerprinting protection reports
# more than one touch point as 5 (nsRFPService::CollapseMaxTouchPoints), and the
# launcher claims what the browser reports (follow_baseline_protection), so 5
# is the only multi-touch value an identity can answer.
CONFIG = {"window.devicePixelRatio": 2.5, "navigator.maxTouchPoints": 5}
PROBE = """() => {
  const f = document.createElement('iframe');
  document.body.appendChild(f);
  const w = f.contentWindow;
  const attached = [w.devicePixelRatio, w.navigator.maxTouchPoints];
  f.remove();
  return {attached, detached: [w.devicePixelRatio, w.navigator.maxTouchPoints]};
}"""


def main() -> int:
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(resolve_binary()), headless=True, os="windows", config=CONFIG,
                  i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content("<body></body>")
        got = page.evaluate(PROBE)
    print(f"  {got}")
    if got["attached"] != [2.5, 5]:
        print("FAIL: an attached frame does not answer the identity's values, so nothing was tested")
        return 1
    if got["detached"] != [1, 0]:
        print(f"FAIL: a removed frame's window answers {got['detached']}, stock's answers [1, 0]")
        return 1
    print("PASS: a removed frame's window answers devicePixelRatio 1 and maxTouchPoints 0, as stock's does")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
