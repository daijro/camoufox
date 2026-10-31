"""
WebDriver BiDi opens windows and switches tabs.

Camoufox ships Firefox's Remote Agent, so `--remote-debugging-port` serves
WebDriver BiDi, which Playwright's `moz-firefox` channel drives. Two of its
steps never finished in Camoufox:

- `WindowManager.openBrowserWindow()` opens a window only for the application
  name "Firefox", so `browsingContext.create` with `type: "window"` failed with
  "openWindow() not supported in Camoufox": every `new_context()` failed.
- `browsingContext.create` for a foreground tab and `browsingContext.activate`
  wait until the tab that was selected reports `visibilityState` "hidden".
  Juggler's page agent, which runs in every loaded page even without
  `--juggler-pipe`, forces its docshell active (`forceActiveState`), so that
  tab stays "visible", no `visibilitychange` comes, and neither command ever
  answered: opening a second tab in a window and every `bring_to_front()`
  between tabs hung.

webdriver-bidi-app-name.patch opens windows for Camoufox as for Firefox, and
webdriver-bidi-force-active.patch does not wait for "hidden" on a docshell that
is forced active. Neither changes what a page observes, so the guard also checks
that the tab put in the background still reports "visible".

Playwright opens every page in a window of its own, so the guard gets a second
tab in one window from window.open() and switches back with bring_to_front()
(browsingContext.activate). Foreground browsingContext.create goes through the
same wait.

A hung sync call cannot be timed out in-process, so the work runs in a child
the parent kills on a hang.

    python browser/tests/playwright/patches/webdriver-bidi-tabs.py --binary /path/to/camoufox-bin
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

CHILD_ENV = "_WEBDRIVER_BIDI_TABS_CHILD"
CHILD_TIMEOUT_S = 90


def run_child() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.firefox.launch(channel="moz-firefox", executable_path=str(resolve_binary()), headless=False)
        page = browser.new_context().new_page()
        print("    new_context() opened a window", flush=True)
        # A loaded document, not the initial about:blank: only a document with
        # Juggler's page agent is forced active.
        page.goto("data:text/html,<title>opener</title>")
        with page.expect_popup() as popup_info:
            page.evaluate("window.open()")
        popup = popup_info.value
        popup.goto("data:text/html,<title>popup</title>")
        print("    window.open() selected a tab over the opener", flush=True)
        page.bring_to_front()
        print("    bring_to_front() selected the opener again", flush=True)
        background = popup.evaluate("document.visibilityState")
        browser.close()
    print(f"    the background tab reports {background!r}", flush=True)
    return 0 if background == "visible" else 2


def main() -> int:
    if os.environ.get(CHILD_ENV):
        return run_child()
    with hidden_display():
        try:
            r = subprocess.run([sys.executable, *sys.argv], env={**os.environ, CHILD_ENV: "1"},
                               timeout=CHILD_TIMEOUT_S, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except subprocess.TimeoutExpired as e:
            sys.stdout.write((e.stdout or b"").decode(errors="replace"))
            print(f"FAIL: hung > {CHILD_TIMEOUT_S}s in the step after the last one printed above")
            return 1
    sys.stdout.write(r.stdout.decode(errors="replace"))
    if r.returncode == 2:
        print("FAIL: a background tab's visibilityState changed; pages would see it")
        return 1
    if r.returncode:
        print(f"FAIL: child exit {r.returncode}")
        return 1
    print("PASS: WebDriver BiDi opens windows and switches tabs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
