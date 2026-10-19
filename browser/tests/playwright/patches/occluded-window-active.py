"""
A page keeps rendering when another browser's window covers its window (#804).

On X11, Firefox marks a window fully occluded when another window covers it,
and deactivates it: Tabbrowser preserves the page's layers and turns its
docshell inactive, and the page's refresh driver falls back to a timer that
doubles its interval every tick and stops for good after 600s. Everything that
waits for a frame then stalls and finally hangs -- Playwright's mouse.wheel
awaits a requestAnimationFrame after every scroll. Several headful browsers on
one Xvfb display with no window manager reach this when a later browser's
window covers an earlier one, and Juggler's focus() does not raise a window
without a window manager, so the page never recovers.

Juggler sets forceAppWindowActive on every browser window, Firefox's switch for
keeping an app window active whether it is occluded or minimized.

The guard launches browser A, then a larger browser B over it on the same
display, and counts A's animation frames over two seconds. Before the fix A ran
one; after it, about 120. Whether a covered window stays deactivated is a race
in how the occlusion events arrive -- 7 coverings in 30 left A rendering on a
build without the fix -- so A is covered by five browsers in turn and has to
keep rendering under every one.

    python browser/tests/playwright/patches/occluded-window-active.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

MIN_FRAMES = 10
COVERINGS = 5
FRAMES_IN_2S = """() => new Promise(resolve => {
  let n = 0;
  const tick = () => { n++; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  setTimeout(() => resolve(n), 2000);
})"""


def probe(binary):
    from playwright.sync_api import sync_playwright

    from camoufox import launch_options

    def launch(p, window):
        return p.firefox.launch(**launch_options(
            headless=False, executable_path=str(binary), os="linux", window=window))

    with sync_playwright() as p:
        covered = launch(p, (1600, 1000)).new_page()
        covered.set_content("<h1>covered</h1>")
        alone = covered.evaluate(FRAMES_IN_2S)
        frames = []
        for _ in range(COVERINGS):
            covering = launch(p, (1700, 1050))
            covering.new_page().set_content("<h1>covering</h1>")
            time.sleep(2)
            frames.append(covered.evaluate(FRAMES_IN_2S))
            covering.close()
        return alone, frames


def main() -> int:
    with hidden_display("1920x1080"):
        alone, frames = probe(resolve_binary())
    print(f"A ran {alone} frames alone and {frames} under each covering window")
    failures = []
    if alone < MIN_FRAMES:
        failures.append("A did not render even before it was covered, so the check proves nothing")
    if min(frames) < MIN_FRAMES:
        failures.append("A stopped rendering once B covered its window")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a covered window's page keeps rendering")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
