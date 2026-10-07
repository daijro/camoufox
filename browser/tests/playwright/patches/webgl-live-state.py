"""
Verify getParameter() reports WebGL render state the page set, not recorded values.

webgl-spoofing.patch answers capability queries (limits, precisions, the
renderer) from the identity's recorded WebGL parameters. Render state is
different: a real context reports back whatever the page last set. The recorded
parameters include COLOR_WRITEMASK, so after gl.colorMask(false, ...) the page
read back the recording's all-true mask, which no real context does.

What PASS means: in WebGL 1 and 2, every piece of state set below reads back
exactly as set.

    python browser/tests/playwright/patches/webgl-live-state.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """(kind) => {
  const gl = document.createElement('canvas').getContext(kind);
  if (!gl) return null;
  gl.colorMask(false, true, false, true);
  gl.viewport(1, 2, 3, 4);
  gl.scissor(5, 6, 7, 8);
  gl.clearColor(0.25, 0.5, 0.75, 1);
  gl.blendColor(0.5, 0.25, 0.125, 0.5);
  gl.depthRange(0.25, 0.75);
  gl.depthMask(false);
  gl.frontFace(gl.CW);
  const read = p => {
    const v = gl.getParameter(p);
    return typeof v === 'object' ? Array.from(v) : [v];
  };
  return {
    COLOR_WRITEMASK: read(gl.COLOR_WRITEMASK),
    VIEWPORT: read(gl.VIEWPORT),
    SCISSOR_BOX: read(gl.SCISSOR_BOX),
    COLOR_CLEAR_VALUE: read(gl.COLOR_CLEAR_VALUE),
    BLEND_COLOR: read(gl.BLEND_COLOR),
    DEPTH_RANGE: read(gl.DEPTH_RANGE),
    DEPTH_WRITEMASK: read(gl.DEPTH_WRITEMASK),
    FRONT_FACE: read(gl.FRONT_FACE),
  };
}"""

EXPECTED = {
    "COLOR_WRITEMASK": [False, True, False, True],
    "VIEWPORT": [1, 2, 3, 4],
    "SCISSOR_BOX": [5, 6, 7, 8],
    "COLOR_CLEAR_VALUE": [0.25, 0.5, 0.75, 1],
    "BLEND_COLOR": [0.5, 0.25, 0.125, 0.5],
    "DEPTH_RANGE": [0.25, 0.75],
    "DEPTH_WRITEMASK": [False],
    "FRONT_FACE": [0x0900],  # CW
}


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    passed = True
    # main_world_eval: the isolated world reads typed arrays only through Xrays.
    async with AsyncCamoufox(headless="virtual", os="linux", main_world_eval=True,
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        for kind in ("webgl", "webgl2"):
            got = await page.evaluate("mw:" + PROBE, kind)
            if got is None:
                passed = False
                print(f"  FAIL {kind}: no context")
                continue
            for name, expected in EXPECTED.items():
                if got[name] == expected:
                    print(f"  PASS {kind} {name}: {got[name]}")
                else:
                    passed = False
                    print(f"  FAIL {kind} {name}: got {got[name]}, set {expected}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
