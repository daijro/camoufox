"""
Verify that spoofed values go through stock Firefox's baseline fingerprinting
protection, and that the canvas placeholder the launchers use for cross-OS
identities still works.

privacy.baselineFingerprintingProtection is on in every stock Firefox window.
Its targets transform the real values, so the spoofed ones must go through
them too, for the claimed platform:

    navigator.maxTouchPoints   collapsed to 5           (touchscreen-fingerprint-spoofing)
    screen.avail*              the screen less the claimed OS's taskbar or
                               menu bar, not the build's (screen-spoofing)
    hardwareConcurrency        left as spoofed: not a baseline target

The launchers add privacy.resistFingerprinting's three canvas targets to the
baseline overrides for an identity on another OS (python/src/camoufox/
host_rendering.py). Readback must then be random, as in LibreWolf; without
them it must be what the machine renders, every time.

WebGPU follows the claimed device (set_webgpu): no navigator.gpu where stock
Firefox has none, and navigator.gpu without an adapter for a Windows identity
whose GPU is not the host's.

Run from any venv that has playwright:
    python browser/tests/playwright/patches/baseline-protections.py
    python browser/tests/playwright/patches/baseline-protections.py --binary /path/to/camoufox-bin

Which binary is tested, in order of precedence:
    --binary <path> | $CAMOUFOX_EXECUTABLE_PATH | $CAMOUFOX_BINARY | the in-tree build
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "python" / "src"))
from camoufox.host_rendering import add_canvas_placeholder, set_webgpu  # noqa: E402
from camoufox.utils import get_pref_env_vars  # noqa: E402

SCREEN = {"screen.width": 1920, "screen.height": 1080}
# A configured available rect that no platform's baseline protection reports.
AVAIL = {"screen.availLeft": 0, "screen.availTop": 0, "screen.availWidth": 1900, "screen.availHeight": 1000}

ORIGIN = "https://camoufox.test/"
# The probe runs as the page's own script: an isolated-world evaluate cannot
# read getImageData's pixels through the Xray.
PAGE = r"""<!doctype html><script>
(async () => {
  const canvas = document.createElement('canvas');
  canvas.width = 200; canvas.height = 60;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 200, 0);
  gradient.addColorStop(0, '#c33'); gradient.addColorStop(1, '#33c');
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, 200, 60);
  ctx.fillStyle = '#fff'; ctx.font = '20px sans-serif'; ctx.fillText('Camoufox 1.2.3', 10, 38);
  const hash = async () => Array.from(new Uint8Array(await crypto.subtle.digest(
      'SHA-256', ctx.getImageData(0, 0, 200, 60).data))).map(b => b.toString(16).padStart(2, '0')).join('');
  const worker = new Worker(URL.createObjectURL(new Blob(
      ['postMessage(navigator.hardwareConcurrency)'], {type: 'text/javascript'})));
  const workerCores = await new Promise(resolve => { worker.onmessage = e => resolve(e.data); });
  document.documentElement.dataset.probe = JSON.stringify({
    cores: navigator.hardwareConcurrency,
    workerCores,
    touchPoints: navigator.maxTouchPoints,
    avail: [screen.availLeft, screen.availTop, screen.availWidth, screen.availHeight],
    canvas: [await hash(), await hash()],
    webgpu: navigator.gpu ? [true, (await navigator.gpu.requestAdapter()) !== null] : [false, false],
  });
})();
</script>"""


async def probe(binary: Path, platform: str, prefs: Dict[str, Any]) -> Dict[str, Any]:
    from playwright.async_api import async_playwright

    config = {
        "navigator.platform": platform,
        "navigator.hardwareConcurrency": 12,
        "navigator.maxTouchPoints": 10,
        **SCREEN,
        **AVAIL,
    }
    # As the launchers pass them: the WebGPU blocklist status is read at startup,
    # before Playwright's own prefs arrive.
    env = {**os.environ, "CAMOU_CONFIG_1": json.dumps(config), **get_pref_env_vars(prefs)}
    async with async_playwright() as p:
        browser = await p.firefox.launch(
            executable_path=str(binary), headless=True, env=env, firefox_user_prefs=prefs
        )
        try:
            page = await browser.new_page()
            await page.route(ORIGIN, lambda route: route.fulfill(content_type="text/html", body=PAGE))
            await page.goto(ORIGIN)
            result = await page.wait_for_function("() => document.documentElement.dataset.probe")
            return json.loads(await result.json_value())
        finally:
            await browser.close()


def check(failures: List[str], label: str, got: Any, want: Any) -> None:
    ok = got == want
    print(f"    [{'ok  ' if ok else 'FAIL'}] {label}: {got}" + ("" if ok else f" (expected {want})"))
    if not ok:
        failures.append(label)


async def main() -> int:
    binary = resolve_binary()
    print(f"Binary: {binary}")
    failures: List[str] = []

    # Taskbar or menu bar per claimed platform, from nsRFPService::GetSpoofedScreenAvailSize.
    avail = {
        "Win32": [0, 0, 1920, 1080 - 48],
        "MacIntel": [0, 25, 1920, 1080 - 76],
        "Linux x86_64": [0, 0, 1920, 1080],
    }
    renders = {}
    for platform, want in avail.items():
        print(f"\n=== {platform} ===")
        got = await probe(binary, platform, {})
        check(failures, f"{platform} cores", got["cores"], 12)
        check(failures, f"{platform} worker cores", got["workerCores"], 12)
        check(failures, f"{platform} touch points", got["touchPoints"], 5)
        check(failures, f"{platform} avail", got["avail"], want)
        check(failures, f"{platform} canvas reads the same twice", got["canvas"][0], got["canvas"][1])
        renders[platform] = got["canvas"][0]
    check(failures, "the canvas is what the machine renders, whatever the claim", len(set(renders.values())), 1)

    check(failures, "this build has no navigator.gpu by default", got["webgpu"], [False, False])

    print("\n=== Win32, canvas placeholder, another GPU ===")
    prefs: Dict[str, Any] = {}
    add_canvas_placeholder(prefs)
    set_webgpu(prefs, "win", ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"), None)
    covered = await probe(binary, "Win32", prefs)
    random_reads = covered["canvas"][0] != covered["canvas"][1] and renders["Win32"] not in covered["canvas"]
    check(failures, "readback is random", random_reads, True)
    check(failures, "nothing else changes", (covered["cores"], covered["touchPoints"]), (12, 5))
    check(failures, "navigator.gpu without an adapter", covered["webgpu"], [True, False])

    print()
    if failures:
        print(f"FAIL: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("PASS: spoofed values go through baseline protection, the canvas placeholder covers readback, and WebGPU follows the claim.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
