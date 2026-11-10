"""
An OffscreenCanvas offers WebGL2 exactly when a canvas element does.

A device fpgen recorded without WebGL2 (the Windows WARP software renderer,
the resistFingerprinting mask) is launched with webgl.enable-webgl2 off, and a
canvas element then has no WebGL2 context. OffscreenCanvas never read that
pref: getContext('webgl2') there returned a context with the device's spoofed
renderer name over the HOST's parameters (MAX_TEXTURE_IMAGE_UNITS 32 where the
identity's WebGL1 says 16, and so on). CreepJS reads WebGL through
OffscreenCanvas and flagged "webgl/webgl2 mirrored params mismatch" on it.
offscreen-webgl2-pref.patch makes OffscreenCanvas follow the pref.

Checked headless: a Windows identity pinned to WARP (no WebGL2 in either), and
one on a GPU with WebGL2 (WebGL2 in both).

    python browser/tests/playwright/patches/offscreen-webgl2-follows-canvas.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

# A page script: evaluate() runs in an isolated world, which cannot read the
# typed arrays some parameters return.
PROBE = """<body><script>
const element = !!document.createElement('canvas').getContext('webgl2');
const offscreen = !!new OffscreenCanvas(16, 16).getContext('webgl2');
document.body.dataset.r = JSON.stringify({element, offscreen});
</script></body>"""

WARP = ("Google Inc. (Microsoft)",
        "ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0), or similar")
WITH_WEBGL2 = ("Google Inc. (NVIDIA)",
               "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar")


def probe(webgl_config):
    from camoufox.sync_api import Camoufox

    with Camoufox(**launch_kwargs(os="windows", webgl_config=webgl_config,
                                  i_know_what_im_doing=True)) as browser:
        page = browser.new_page()
        page.set_content(PROBE)
        return json.loads(page.get_attribute("body", "data-r"))


def main() -> int:
    failures = []
    for name, gpu, want in (("WARP, no WebGL2", WARP, False), ("GTX 980, WebGL2", WITH_WEBGL2, True)):
        got = probe(gpu)
        if got != {"element": want, "offscreen": want}:
            failures.append(f"{name}: canvas element webgl2={got['element']}, "
                            f"OffscreenCanvas webgl2={got['offscreen']}, want both {want}")
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("PASS: OffscreenCanvas offers WebGL2 exactly when a canvas element does")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
