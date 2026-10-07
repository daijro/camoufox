r"""
Verify a Camoufox window shows no automation cue in the browser UI.

Two cues a real Firefox never draws, neither readable by page JS:

  78. Every Playwright browser context is a Firefox container. A PUBLIC container
      renders its name ("JUGGLER <id>") and colour in the URL bar and tab strip.
      additions/juggler/TargetRegistry.js marks juggler's identities non-public.
  79. browser-init.patch adds a #cursor-highlighter dot following the mouse when
      the `showcursor` config is true -- and the default used to be true.

The guard launches camoufox through Playwright, headed on a private Xvfb display,
with Marionette also enabled so the chrome document can be inspected. It opens a
page in a new browser context, moves the mouse, and asserts: the tab really is in
a juggler container (usercontextid > 0, so the check is not vacuous), that
container is not a public identity, #userContext-icons is hidden, and no
#cursor-highlighter exists. A second launch with showcursor=true asserts the
opt-in still creates the element, so the id being checked is the real one.

    python browser/tests/playwright/patches/visible-automation-cues.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, resolve_binary  # noqa: E402

JS = """
const out = [];
for (const win of Services.wm.getEnumerator("navigator:browser")) {
  const ids = win.gBrowser.browsers.map(b => Number(b.getAttribute("usercontextid") || 0));
  out.push({
    userContextIds: ids,
    publicIdentities: ids.filter(id => id > 0 && ContextualIdentityService.getPublicIdentityFromId(id)),
    iconsHidden: win.document.getElementById("userContext-icons")?.hidden ?? true,
    label: win.document.getElementById("userContext-label")?.textContent || "",
    cursorHighlighter: !!win.document.getElementById("cursor-highlighter"),
  });
}
return out;
"""


def inspect(binary: Path, display: str, config=None):
    from camoufox.sync_api import Camoufox
    port = free_port()
    os.environ.update(DISPLAY=display, MOZ_ENABLE_WAYLAND="0", GDK_BACKEND="x11")
    os.environ.pop("WAYLAND_DISPLAY", None)
    with Camoufox(headless=False, executable_path=str(binary), args=marionette_args(),
                  firefox_user_prefs={"marionette.port": port}, config=config or {},
                  i_know_what_im_doing=True) as browser:
        context = browser.new_context()
        page = context.new_page()
        page.goto("about:blank")
        page.mouse.move(400, 300)
        time.sleep(2)
        m = Marionette(port)
        try:
            return m.js(JS)
        finally:
            m.close()


def main() -> int:
    binary = resolve_binary()
    failures = []
    with hidden_display() as display:
        windows = inspect(binary, display)
        for w in windows:
            print(f"  window: contexts={w['userContextIds']} public={w['publicIdentities']} "
                  f"iconsHidden={w['iconsHidden']} label={w['label']!r} cursorHighlighter={w['cursorHighlighter']}")
        if not any(i > 0 for w in windows for i in w["userContextIds"]):
            failures.append("no tab in a juggler container -- the container check would be vacuous")
        if any(w["publicIdentities"] for w in windows):
            failures.append("a juggler container is a PUBLIC identity (URL-bar label shown)")
        if not all(w["iconsHidden"] for w in windows):
            failures.append("#userContext-icons is visible")
        if any(w["cursorHighlighter"] for w in windows):
            failures.append("#cursor-highlighter exists with the default config")

        opted_in = inspect(binary, display, config={"showcursor": True})
        print(f"  showcursor=true -> cursorHighlighter={[w['cursorHighlighter'] for w in opted_in]}")
        if not any(w["cursorHighlighter"] for w in opted_in):
            failures.append("showcursor=true no longer creates #cursor-highlighter (checked id is stale)")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: no container label and no cursor overlay in the browser UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
