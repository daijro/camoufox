"""
A right click fires its events in the claimed OS's order.

People's right clicks on stock 159.0 (private recordings, a mouse and a
touchpad on each OS):
- Windows shows the menu on release: pointerdown, mousedown, pointerup,
  mouseup, auxclick, contextmenu.
- macOS shows it on press: pointerdown, mousedown, contextmenu, pointerup,
  mouseup, auxclick.
GTK shows it on press, as macOS does.

The guard right-clicks under each identity and checks the sequence, and that
the contextmenu reports the buttons held at that moment.

    python browser/tests/playwright/patches/driven-right-click-order.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><html><body style="margin:0;width:800px;height:600px"><script>
  const seen = [];
  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'auxclick', 'click', 'contextmenu'])
    addEventListener(type, (e) => {
      seen.push([type, e.buttons]);
      document.body.dataset.seen = JSON.stringify(seen);
      if (type === 'contextmenu') e.preventDefault();
    }, true);
</script></body></html>"""

ON_RELEASE = ["pointerdown", "mousedown", "pointerup", "mouseup", "auxclick", "contextmenu"]
ON_PRESS = ["pointerdown", "mousedown", "contextmenu", "pointerup", "mouseup", "auxclick"]
EXPECTED = {"windows": (ON_RELEASE, 0), "macos": (ON_PRESS, 2), "linux": (ON_PRESS, 2)}


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(binary), headless=False, os=os_name, i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.mouse.move(200, 200)
        page.mouse.click(200, 200, button="right")
        page.wait_for_timeout(200)
        return page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')")


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        seen = {os_name: probe(resolve_binary(), os_name) for os_name in EXPECTED}
    for os_name, (order, buttons) in EXPECTED.items():
        got = [t for t, _ in seen[os_name]]
        if got != order:
            failures.append(f"{os_name}: {got}, a person's right click gives {order}")
        menu = [b for t, b in seen[os_name] if t == "contextmenu"]
        if menu != [buttons]:
            failures.append(f"{os_name}: contextmenu buttons {menu}, a person's gives [{buttons}]")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a right click fires in the claimed OS's order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
