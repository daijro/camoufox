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
(microsoft/playwright#41859). Camoufox's never does: RDM matches no real
browser (Firefox for Android does not run it), and Camoufox only has desktop
identities, so the launchers warn about is_mobile instead. The guard pins
classic scrollbars and measures the scrollbar gutter three ways:

  - a launch-level page, the control: it must be non-zero, or the check is
    vacuous;
  - a context with a viewport, which must match the control;
  - a context with a viewport and is_mobile=True, which must match it too.

RDM plus touch also swallowed the pointer events of a mouse click
(PointerEventHandler): in a desktop context with has_touch=True, page.click()
fired mousedown, mouseup and click with no pointerdown or pointerup, which
stock Firefox never does. The guard clicks a button in such a context and
requires the same event sequence as on the launch-level page.

    python tests/patches/viewport-no-rdm.py
"""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

VIEWPORT = {"width": 1000, "height": 600}

PAGE = """<!doctype html><style>body{margin:0;height:3000px}
#b{width:200px;height:100px;overflow:scroll}</style><div id=b></div>"""

# The events land in an attribute: page.evaluate runs in an isolated world and
# cannot read the page's globals.
CLICK_PAGE = """<!doctype html><button id=t style="width:200px;height:80px">x</button><script>
for (const k of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'])
  t.addEventListener(k, () => t.dataset.ev = (t.dataset.ev ? t.dataset.ev + ' ' : '') + k);
</script>"""

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


def click_events(page) -> str:
    page.set_content(CLICK_PAGE)
    page.click("#t")
    return page.get_attribute("#t", "data-ev") or ""


def main() -> int:
    from camoufox._warnings import LeakWarning
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    with Camoufox(os="linux", headless=True, executable_path=str(binary),
                  firefox_user_prefs={"ui.useOverlayScrollbars": 0},
                  i_know_what_im_doing=True) as browser:
        control = measure(browser.new_page(no_viewport=True))
        emulated = measure(browser.new_context(viewport=VIEWPORT).new_page())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LeakWarning)  # is_mobile warns; that is the point
            mobile = measure(browser.new_context(viewport=VIEWPORT, is_mobile=True).new_page())
        control_click = click_events(browser.new_page(no_viewport=True))
        touch_click = click_events(browser.new_context(viewport=VIEWPORT, has_touch=True).new_page())

    print(f"  launch page:      {control}")
    print(f"  viewport context: {emulated}")
    print(f"  is_mobile:        {mobile}")
    print(f"  click, launch page:           {control_click}")
    print(f"  click, viewport + has_touch:  {touch_click}")

    failures = []
    if control["page"] <= 0 or control["box"] <= 0:
        failures.append(f"launch page shows no classic scrollbar ({control}): the check is vacuous")
    if emulated["viewport"] != [VIEWPORT["width"], VIEWPORT["height"]]:
        failures.append(f"viewport {VIEWPORT} not applied: page reports {emulated['viewport']}")
    if (emulated["page"], emulated["box"]) != (control["page"], control["box"]):
        failures.append(
            f"scrollbar width differs with a viewport: {emulated['page']}/{emulated['box']} px "
            f"vs {control['page']}/{control['box']} px without (Responsive Design Mode)")
    if (mobile["page"], mobile["box"]) != (control["page"], control["box"]):
        failures.append(
            f"scrollbar width differs with is_mobile=True: {mobile['page']}/{mobile['box']} px "
            f"vs {control['page']}/{control['box']} px without (Responsive Design Mode)")
    if "pointerdown" not in control_click:
        failures.append(f"a click on the launch page fired no pointerdown ({control_click!r}): the check is vacuous")
    if touch_click != control_click:
        failures.append(
            f"a click with has_touch fired {touch_click!r}, not {control_click!r} "
            "(Responsive Design Mode drops a mouse click's pointer events)")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: no context enters Responsive Design Mode -- a viewport keeps the platform's scrollbars, is_mobile included, and a click keeps its pointer events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
