"""
Verify the touchscreen digitizer spoof (touchscreen-fingerprint-spoofing.patch
plus the any-pointer half of force-default-pointer.patch).

Setting `navigator.maxTouchPoints` above zero has to produce the fingerprint of
a touchscreen *laptop*, not of a phone. Three things must move together:

    navigator.maxTouchPoints   the digitizer is reported          (Navigator.cpp)
    (any-pointer: coarse)      it joins the any- pointer set      (nsMediaFeatures.cpp)
    window.TouchEvent/Touch    the touch interfaces appear        (TouchEvent.cpp)

and three things must deliberately NOT move:

    (pointer: coarse)          stays false -- the trackpad is still primary
    (hover: hover)             stays true  -- so does hovering
    'ontouchstart' in window   stays false -- legacy_apis is off on desktop

The last one is the subtle one. `ontouchstart` is gated by LegacyAPIEnabled,
not PrefEnabled, and dom.w3c_touch_events.legacy_apis.enabled defaults to
false everywhere but Android. A real Windows touchscreen laptop therefore
exposes TouchEvent while `'ontouchstart' in window` is false, and a build that
turns on "touch support" wholesale is *more* detectable than one that does
nothing.

Run from any venv that has playwright:
    python tests/patches/touchscreen-digitizer.py
    python tests/patches/touchscreen-digitizer.py --binary /path/to/camoufox-bin

Which binary is tested, in order of precedence:
    --binary <path> | $CAMOUFOX_BINARY | the in-tree obj-*/dist/bin/camoufox-bin
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

# The digitizer count the reference was recorded with.
SPOOFED_TOUCH_POINTS = 5

# ---------------------------------------------------------------------------
# The recorded reference: a Dell XPS 15 9510 (Windows 10, touchscreen) running
# Firefox 152.0, captured with tests/patches/assets/touch-reference.html.
#
#   UA        Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0)
#             Gecko/20100101 Firefox/152.0
#   platform  Win32          screen  1382x864 @ dpr 2.5
#
# These are the sixteen static touch signals from that capture, verbatim. The
# recording also carries 284 input events and eight context values (screen,
# dpr, hardwareConcurrency, ...) which are not touch signals and are not
# asserted here.
#
# Two of these are easy to get wrong from first principles, so note them:
#
#   createTouch  is FALSE. document.createTouch is a legacy API gated by
#     TouchEvent::LegacyAPIEnabled, the same gate as ontouchstart, and
#     dom.w3c_touch_events.legacy_apis.enabled is false off Android. A real
#     touchscreen laptop exposes TouchEvent while createTouch stays absent.
#   PointerEvent is TRUE, and unconditionally so -- it is not gated on a
#     digitizer at all. It is listed to pin that it must not start varying.
# ---------------------------------------------------------------------------
RECORDED: Dict[str, Any] = {
    # --- touch API surface ---
    "navigator.maxTouchPoints": SPOOFED_TOUCH_POINTS,
    "'ontouchstart' in window": False,
    "window.TouchEvent": True,
    "window.Touch": True,
    "document.createTouch": False,
    "window.PointerEvent": True,
    # --- CSS pointer/hover media queries ---
    "(pointer: coarse)": False,
    "(pointer: fine)": True,
    "(pointer: none)": False,
    "(any-pointer: coarse)": True,
    "(any-pointer: fine)": True,
    "(any-pointer: none)": False,
    "(hover: hover)": True,
    "(hover: none)": False,
    "(any-hover: hover)": True,
    "(any-hover: none)": False,
}

# Collected and printed, never asserted on -- none of these is in the recording,
# so there is no measured value to hold them to:
#
#   window.TouchList  shares TouchEvent's gate, so it tracks TouchEvent and
#     flips with it. Worth seeing, but it would just restate that assertion.
#   document.createEvent('TouchEvent')  gated by LegacyAPIEnabled, like
#     createTouch, so it is false on desktop.
#   'ontouchstart' on document / documentElement  the same mixin as the window
#     one, printed to show all three agree.
INFORMATIONAL = (
    "window.TouchList",
    "document.createEvent('TouchEvent')",
    "'ontouchstart' in document",
    "'ontouchstart' in documentElement",
)

# maxTouchPoints=0 must look exactly like a machine with no digitizer, or the
# patch has leaked touch capability into every ordinary launch.
NO_DIGITIZER: Dict[str, Any] = {
    "(pointer: fine)": True,
    "(pointer: coarse)": False,
    "(any-pointer: fine)": True,
    "(any-pointer: coarse)": False,
    "(hover: hover)": True,
    "(any-hover: hover)": True,
    "navigator.maxTouchPoints": 0,
    "window.TouchEvent": False,
    "window.Touch": False,
    "'ontouchstart' in window": False,
}

PROBE_JS = r"""() => {
  const mq = q => window.matchMedia(q).matches;
  let createEvent = false;
  try { createEvent = !!document.createEvent('TouchEvent'); } catch (e) { createEvent = false; }
  let createTouch = false;
  try { createTouch = typeof document.createTouch === 'function'; } catch (e) { createTouch = false; }
  return {
    "(pointer: fine)":       mq("(pointer: fine)"),
    "(pointer: coarse)":     mq("(pointer: coarse)"),
    "(pointer: none)":       mq("(pointer: none)"),
    "(any-pointer: fine)":   mq("(any-pointer: fine)"),
    "(any-pointer: coarse)": mq("(any-pointer: coarse)"),
    "(any-pointer: none)":   mq("(any-pointer: none)"),
    "(hover: hover)":        mq("(hover: hover)"),
    "(hover: none)":         mq("(hover: none)"),
    "(any-hover: hover)":    mq("(any-hover: hover)"),
    "(any-hover: none)":     mq("(any-hover: none)"),
    "navigator.maxTouchPoints":          navigator.maxTouchPoints,
    "window.TouchEvent":                 "TouchEvent" in window,
    "window.Touch":                      "Touch" in window,
    "document.createTouch":              createTouch,
    "window.PointerEvent":               "PointerEvent" in window,
    "'ontouchstart' in window":          "ontouchstart" in window,
    "'ontouchstart' in document":        "ontouchstart" in document,
    "'ontouchstart' in documentElement": "ontouchstart" in document.documentElement,
    "window.TouchList":                  "TouchList" in window,
    "document.createEvent('TouchEvent')": createEvent
  };
}"""


def resolve_binary(argv) -> Optional[Path]:
    if "--binary" in argv:
        return Path(argv[argv.index("--binary") + 1]).resolve()
    if os.environ.get("CAMOUFOX_BINARY"):
        return Path(os.environ["CAMOUFOX_BINARY"]).resolve()
    matches = sorted(REPO_ROOT.glob("camoufox-*/obj-*/dist/bin/camoufox-bin"))
    return matches[-1] if matches else None


async def probe(binary: Path, max_touch_points: Optional[int]) -> Dict[str, Any]:
    """Launch the binary with a config and read every touch signal back."""
    from playwright.async_api import async_playwright

    config: Dict[str, Any] = {}
    if max_touch_points is not None:
        config["navigator.maxTouchPoints"] = max_touch_points

    env = dict(os.environ)
    env["CAMOU_CONFIG_1"] = json.dumps(config)

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            executable_path=str(binary), headless=True, env=env
        )
        try:
            page = await browser.new_page()
            await page.goto("about:blank")
            return await page.evaluate(PROBE_JS)
        finally:
            await browser.close()


def compare(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    """Print a per-signal table. True only if every expected signal matches."""
    missing = sorted(set(expected) - set(actual))
    if missing:
        print(f"  FAIL: probe never collected: {', '.join(missing)}")
        return False

    width = max(len(k) for k in expected)
    failures = 0
    for name, want in expected.items():
        got = actual[name]
        ok = want == got
        failures += not ok
        mark = "ok  " if ok else "FAIL"
        detail = f"{str(got):<7}" if ok else f"{str(got):<7} (expected {want})"
        print(f"    [{mark}] {name:<{width}}  {detail}")

    print(f"\n  {len(expected) - failures}/{len(expected)} signals match")
    return failures == 0


async def main() -> int:
    binary = resolve_binary(sys.argv)
    if binary is None or not binary.exists():
        print(f"FATAL: no camoufox binary found (looked for {binary})")
        return 1

    print(f"Binary: {binary}")

    print(f"\n=== navigator.maxTouchPoints = {SPOOFED_TOUCH_POINTS} "
          f"(vs recorded reference) ===")
    spoofed = await probe(binary, SPOOFED_TOUCH_POINTS)
    matched = compare(spoofed, RECORDED)
    for name in INFORMATIONAL:
        print(f"    [info] {name} = {spoofed[name]}")

    print("\n=== navigator.maxTouchPoints = 0 (control) ===")
    control_ok = compare(await probe(binary, 0), NO_DIGITIZER)

    print()
    if matched and control_ok:
        print("PASS: the spoofed fingerprint matches the recording, and "
              "maxTouchPoints=0 is untouched.")
        return 0
    if not matched:
        print("FAIL: the spoofed fingerprint does not match the recording.")
    if not control_ok:
        print("FAIL: maxTouchPoints=0 no longer looks like a machine without a digitizer.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
