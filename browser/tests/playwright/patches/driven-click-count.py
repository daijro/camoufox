"""
Driven presses count clicks as the claimed OS does.

The OS, not the page, decides a press's click count (`detail`): a press in
place soon after the last one counts up. People's recordings on stock 159.0
(private, a mouse and a touchpad on each OS) follow these rules, checked
against every recorded press:
- Windows: Firefox counts a press within 500 ms of the last one, unless the
  pointer moved 4 device pixels from the last release; Windows itself reports
  a press within 1 device pixel of the last single press as a double click,
  which sets the count to 2. Fifteen quick presses in place count
  1, 2, 3, 2, 3, ...
- macOS: a press within 500 ms and 3 points of the last one counts up, without
  bound.
- GTK counts 1, 2, 3 and starts again, within its default 400 ms and 5 pixels.
A driven press always reported the clickCount the client sent: 1 for every
page.click(), however quick and wherever.

The guard presses in place under each identity, then presses after a pause
and after a move, and checks every count.

    python browser/tests/playwright/patches/driven-click-count.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:0;width:800px;height:600px"><script>
  const seen = [];
  for (const type of ['mousedown', 'mouseup', 'click'])
    addEventListener(type, (e) => {
      seen.push([type, e.detail]);
      document.body.dataset.seen = JSON.stringify(seen);
    }, true);
</script></body></html>"""
PRESSES = 8
IN_PLACE = {
    "windows": [1, 2, 3, 2, 3, 2, 3, 2],
    "macos": [1, 2, 3, 4, 5, 6, 7, 8],
    "linux": [1, 2, 3, 1, 2, 3, 1, 2],
}


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os=os_name, i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.mouse.move(200, 200)
        for _ in range(PRESSES):
            page.mouse.click(200, 200)
            page.wait_for_timeout(60)
        page.wait_for_timeout(700)
        page.mouse.click(200, 200)
        page.mouse.move(260, 200)
        page.mouse.click(260, 200)
        page.wait_for_timeout(100)
        return page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')")


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        seen = {os_name: probe(resolve_binary(), os_name) for os_name in IN_PLACE}
    for os_name, counts in IN_PLACE.items():
        expected = counts + [1, 1]
        downs = [d for t, d in seen[os_name] if t == "mousedown"]
        if downs != expected:
            failures.append(f"{os_name}: presses counted {downs}, a person's count {expected}")
        for kind in ("mouseup", "click"):
            got = [d for t, d in seen[os_name] if t == kind]
            if got != expected:
                failures.append(f"{os_name}: {kind} detail {got}, its press counted {expected}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: driven presses count clicks as each OS does")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
