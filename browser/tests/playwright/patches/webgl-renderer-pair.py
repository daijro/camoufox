r"""
Every WebGL context names its own browser context's GPU, as in stock Firefox.

Stock answers `gl.getParameter(gl.RENDERER)` and the debug extension's
UNMASKED_RENDERER_WEBGL with the same sanitized string, and VENDOR with
"Mozilla". webgl-spoofing.patch answered UNMASKED_RENDERER_WEBGL from the
identity but RENDERER from the real context, so a page read the host's GPU next
to the spoofed one (#839).

A context's GPU is looked up by its userContextId. Taking that from the
document's browsing context gave 0 for documents that have none
(`document.implementation.createHTMLDocument()`, DOMParser), and the setters
also wrote slot 0, so a canvas in such a document reported whichever context set
its GPU last. Two contexts claim two different GPUs (different vendors), set one
after the other, and each reads its own on the page, in a data document, in a
DOMParser document and in a worker (OffscreenCanvas).

With the WebGLRenderInfo fingerprinting-protection target on, stock answers
"Mozilla" for RENDERER and both UNMASKED_* strings; the spoofed GPU must not
appear next to it.

Checked on a virtual display so the WebGL context is real.

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
            ext && gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),
            ext && gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)];
  };
  const out = {};
  for (const kind of ['webgl', 'webgl2'])
    out[kind] = read(document.createElement('canvas').getContext(kind));
  const dataDoc = document.implementation.createHTMLDocument('');
  out.dataDocument = read(dataDoc.createElement('canvas').getContext('webgl'));
  const parsed = new DOMParser().parseFromString('<canvas></canvas>', 'text/html');
  out.domParser = read(parsed.querySelector('canvas').getContext('webgl'));
  const src = 'const read = ' + read.toString() +
    '; postMessage(read(new OffscreenCanvas(1, 1).getContext("webgl")))';
  const worker = new Worker(URL.createObjectURL(new Blob([src])));
  out.worker = await new Promise(r => { worker.onmessage = e => r(e.data); worker.onerror = e => r(String(e.message)); });
  return JSON.stringify(out);
}"""


def check(label, out, expected):
    """Failures where a probe in `out` does not read [VENDOR, RENDERER,
    UNMASKED_VENDOR, UNMASKED_RENDERER] == expected."""
    failures = []
    for where, got in out.items():
        if not isinstance(got, list):
            failures.append(f"{label} {where}: no WebGL context ({got!r})")
        elif got != expected:
            failures.append(f"{label} {where}: read {got}, expected {expected}")
    return failures


async def run(binary, gpus):
    from camoufox.async_api import AsyncCamoufox

    launch_gpu, *context_gpus = gpus
    failures = []
    async with AsyncCamoufox(headless="virtual", os="linux", executable_path=str(binary),
                             webgl_config=launch_gpu, i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        failures += check("launch", json.loads(await page.evaluate(PROBE)),
                          ["Mozilla", launch_gpu[1], *launch_gpu])

        # Each context sets its GPU in turn, then all are probed: a lookup that
        # misses its own context reads the one set last.
        pages = []
        for vendor, renderer in context_gpus:
            context = await browser.new_context()
            await context.add_init_script(
                f"setWebGLVendor({json.dumps(vendor)}); setWebGLRenderer({json.dumps(renderer)});"
            )
            pages.append(await context.new_page())
            await pages[-1].goto("about:blank")
        for gpu, context_page in zip(context_gpus, pages):
            failures += check(gpu[1], json.loads(await context_page.evaluate(PROBE)),
                              ["Mozilla", gpu[1], *gpu])

    async with AsyncCamoufox(headless="virtual", os="linux", executable_path=str(binary),
                             webgl_config=launch_gpu, i_know_what_im_doing=True,
                             firefox_user_prefs={
                                 "privacy.fingerprintingProtection": True,
                                 "privacy.fingerprintingProtection.overrides": "+WebGLRenderInfo",
                             }) as browser:
        page = await browser.new_page()
        await page.goto("about:blank")
        failures += check("WebGLRenderInfo", json.loads(await page.evaluate(PROBE)),
                          ["Mozilla"] * 4)
    return failures


def main() -> int:
    from camoufox.fingerprints import is_software_renderer
    from camoufox.webgl import firefox_gpus

    gpus = sorted(gpu for gpu in firefox_gpus("linux") if not is_software_renderer(gpu[1]))
    # The launch GPU, then two contexts' GPUs from different vendors.
    picked = [gpus[0], gpus[1], next(gpu for gpu in gpus if gpu[0] != gpus[1][0])]
    failures = asyncio.run(run(resolve_binary(), picked))
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: every context reads its own GPU in pages, data documents and workers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
