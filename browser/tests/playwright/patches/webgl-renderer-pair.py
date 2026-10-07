r"""
RENDERER and UNMASKED_RENDERER_WEBGL name the same GPU, as in stock Firefox.

Stock answers `gl.getParameter(gl.RENDERER)` and the debug extension's
UNMASKED_RENDERER_WEBGL with the same sanitized string, and VENDOR with
"Mozilla". webgl-spoofing.patch answered UNMASKED_RENDERER_WEBGL from the
identity but RENDERER from the real context, so a page read the host's GPU next
to the spoofed one:

    gl.getParameter(gl.RENDERER) !== gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)

Checked on a page and in a worker (OffscreenCanvas), for WebGL 1 and 2, on a
virtual display so the context is real.

    python browser/tests/playwright/patches/webgl-renderer-pair.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """async () => {
  const read = (gl) => {
    if (!gl) return null;
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return [gl.getParameter(gl.VENDOR), gl.getParameter(gl.RENDERER),
            ext && gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)];
  };
  const out = {};
  for (const kind of ['webgl', 'webgl2'])
    out[kind] = read(document.createElement('canvas').getContext(kind));
  const src = 'const read = ' + read.toString() +
    '; postMessage(read(new OffscreenCanvas(1, 1).getContext("webgl")))';
  const worker = new Worker(URL.createObjectURL(new Blob([src])));
  out.worker = await new Promise(r => { worker.onmessage = e => r(e.data); worker.onerror = e => r(String(e.message)); });
  return JSON.stringify(out);
}"""


async def probe(binary):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless="virtual", os="linux", executable_path=str(binary),
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        return json.loads(await page.evaluate(PROBE))


def main() -> int:
    out = asyncio.run(probe(resolve_binary()))
    print(out)
    failures = []
    for where, got in out.items():
        if not isinstance(got, list):
            failures.append(f"{where}: no WebGL context ({got!r})")
            continue
        vendor, renderer, unmasked = got
        if vendor != "Mozilla":
            failures.append(f"{where}: VENDOR is {vendor!r}, stock answers 'Mozilla'")
        if renderer != unmasked:
            failures.append(f"{where}: RENDERER {renderer!r} but UNMASKED_RENDERER_WEBGL {unmasked!r}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: RENDERER and UNMASKED_RENDERER_WEBGL agree on the page and in workers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
