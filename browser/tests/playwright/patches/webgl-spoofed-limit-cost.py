"""
A spoofed WebGL limit costs what stock pays for it: the synchronous host fetch.

Stock Firefox keeps a few WebGL limits client-side (MAX_TEXTURE_SIZE, ...), but
for most (MAX_RENDERBUFFER_SIZE, SUBPIXEL_BITS, MAX_*_UNIFORM_*, ...)
getParameter() sends a synchronous Msg_GetNumber to the GPU host on every call,
while isEnabled(cap) is answered from client state. A page timing the two reads
~1000x on stock 158.0.1 (Linux). webgl-spoofing.patch answered an identity's
webGl:parameters entry from the table and returned before that fetch, so a
spoofed limit read ~1.5x: a stopwatch tell, on every launch with a drawn WebGL
identity. GetParameter now still makes the fetch and discards it.

Checks (headless, Linux identity): getParameter() of two spoofed limits returns
the identity's value AND, counted in fixed 25 ms windows, runs at least 20x
fewer calls than isEnabled(BLEND).

    python browser/tests/playwright/patches/webgl-spoofed-limit-cost.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

MAX_RENDERBUFFER_SIZE, SUBPIXEL_BITS = 0x84E8, 0x0D50
SPOOF = {str(MAX_RENDERBUFFER_SIZE): 8192, str(SUBPIXEL_BITS): 4}

PROBE = """() => {
  const gl = document.createElement('canvas').getContext('webgl');
  if (!gl) return { error: 'no webgl' };
  const rate = (f) => { let n = 0; const s = performance.now(); while (performance.now() - s < 25) { for (let i = 0; i < 32; i++) f(); n += 32; } return n; };
  const out = {};
  for (const [name, pname] of [['MAX_RENDERBUFFER_SIZE', gl.MAX_RENDERBUFFER_SIZE], ['SUBPIXEL_BITS', gl.SUBPIXEL_BITS]]) {
    const r = [];
    for (let k = 0; k < 5; k++) r.push(rate(() => gl.isEnabled(gl.BLEND)) / rate(() => gl.getParameter(pname)));
    r.sort((a, b) => a - b);
    out[name] = { value: gl.getParameter(pname), ratio: r[2] };
  }
  return out;
}"""


def main() -> int:
    from camoufox.sync_api import Camoufox

    with Camoufox(executable_path=str(resolve_binary()), headless=True, os="linux",
                  config={"webGl:parameters": SPOOF}, i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.goto("about:blank")
        got = page.evaluate(PROBE)
    if "error" in got:
        print(f"FAIL: {got['error']}")
        return 1
    errors = []
    for name, want in (("MAX_RENDERBUFFER_SIZE", 8192), ("SUBPIXEL_BITS", 4)):
        g = got[name]
        print(f"  {name}: value {g['value']} (spoofed {want}), isEnabled/getParameter {g['ratio']:.1f}x")
        if g["value"] != want:
            errors.append(f"{name}: {g['value']}, want the identity's {want}")
        if g["ratio"] < 20:
            errors.append(f"{name}: getParameter runs {g['ratio']:.1f}x isEnabled's cost; stock pays a sync host "
                          "fetch (~1000x)")
    for e in errors:
        print(f"FAIL: {e}")
    if errors:
        return 1
    print("PASS: spoofed limits keep the identity's value and stock's fetch cost")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
