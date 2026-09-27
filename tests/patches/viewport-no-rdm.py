r"""
An emulated viewport must not put the page in Responsive Design Mode.

Juggler used to set `browsingContext.inRDMPane = true` for every page with a
viewport, which is the default for new_context(). RDM is devtools' mobile mode:
Gecko draws content with the Android theme and overlay scrollbars
(nsPresContext::UseOverlayScrollbars), and stock getters take RDM early returns
(nsScreen, Navigator::MaxTouchPoints). A page can read both. With classic
scrollbars pinned, a desktop identity measured 12 px of scrollbar on a
launch-level page and 0 px in any context with a viewport.

Playwright's Juggler now enables RDM only for `isMobile`
(microsoft/playwright#41859), and so does Camoufox's. The guard pins classic
scrollbars and measures the scrollbar gutter three ways:

  - a launch-level page, the control: it must be non-zero, or the check is
    vacuous;
  - a context with a viewport, which must match the control;
  - a context with a viewport and is_mobile=True, which must still get RDM's
    overlay scrollbars, so the option the caller asked for is not dropped.

    python tests/patches/viewport-no-rdm.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

VIEWPORT = {"width": 1000, "height": 600}

PAGE = """<!doctype html><style>body{margin:0;height:3000px}
#b{width:200px;height:100px;overflow:scroll}</style><div id=b></div>"""

MEASURE = """() => {
  const b = document.getElementById('b');
  return {
    page: innerWidth - document.documentElement.clientWidth,
    box: b.offsetWidth - b.clientWidth,
    viewport: [innerWidth, innerHeight],
  };
}"""


def measure(page) -> dict:
    page.set_content(PAGE)
    return page.evaluate(MEASURE)


def main() -> int:
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    with Camoufox(os="linux", headless=True, executable_path=str(binary),
                  firefox_user_prefs={"ui.useOverlayScrollbars": 0},
                  i_know_what_im_doing=True) as browser:
        control = measure(browser.new_page(no_viewport=True))
        emulated = measure(browser.new_context(viewport=VIEWPORT).new_page())
        mobile = measure(browser.new_context(viewport=VIEWPORT, is_mobile=True).new_page())

    print(f"  launch page:      {control}")
    print(f"  viewport context: {emulated}")
    print(f"  is_mobile:        {mobile}")

    failures = []
    if control["page"] <= 0 or control["box"] <= 0:
        failures.append(f"launch page shows no classic scrollbar ({control}): the check is vacuous")
    if emulated["viewport"] != [VIEWPORT["width"], VIEWPORT["height"]]:
        failures.append(f"viewport {VIEWPORT} not applied: page reports {emulated['viewport']}")
    if (emulated["page"], emulated["box"]) != (control["page"], control["box"]):
        failures.append(
            f"scrollbar width differs with a viewport: {emulated['page']}/{emulated['box']} px "
            f"vs {control['page']}/{control['box']} px without (Responsive Design Mode)")
    if (mobile["page"], mobile["box"]) != (0, 0):
        failures.append(
            f"is_mobile=True did not enable Responsive Design Mode: scrollbars measure "
            f"{mobile['page']}/{mobile['box']} px, not RDM's 0/0 overlay")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: a viewport keeps the platform's scrollbars; only is_mobile enables Responsive Design Mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
