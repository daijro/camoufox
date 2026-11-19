"""What this machine renders, and covering it when the identity claims another machine.

A page can draw a canvas or a WebGL scene and read the pixels back, and those
pixels come from the real OS, driver and GPU whatever the identity claims. On
the host's own OS the identity claims the GPU the host renders with, so the
pixels agree with it. An identity on another OS, or naming another GPU,
cannot agree, so its canvas readback is replaced with random data, as
privacy.resistFingerprinting does in LibreWolf, Tor Browser and Mullvad
Browser. Stock Firefox does not do that.
WebGPU hands the page the host's adapter, so the identity gets it only when it
claims the host's GPU.
"""

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .fingerprints import is_software_renderer
from .gpudisplay import GPU_PREFS

BASELINE_OVERRIDES_PREF = 'privacy.baselineFingerprintingProtection.overrides'

# The canvas targets privacy.resistFingerprinting turns on, and only those:
# readback without the site's permission returns random data.
CANVAS_PLACEHOLDER_TARGETS = (
    '+CanvasImageExtractionPrompt',
    '+CanvasExtractionBeforeUserInputIsBlocked',
    '+CanvasExtractionFromThirdPartiesIsBlocked',
)

# The downloadable blocklist's pref for WebGPU and its nsIGfxInfo statuses
# (widget/GfxInfoFeatureStatusDefs.inc). A blocked device resolves
# requestAdapter() to null, as on a machine whose GPU Firefox blocks.
WEBGPU_BLOCKLIST_PREF = 'gfx.blacklist.webgpu'
FEATURE_STATUS_OK = 1
FEATURE_BLOCKED_DEVICE = 4

# What the launcher itself adds to the browser's environment; none of it
# changes which device Firefox renders on.
_LAUNCHER_ENV = ('CAMOU_', 'FONTCONFIG_FILE')

Gpu = Tuple[str, str]

# A display that accepts TCP but never completes the X handshake leaves Firefox's
# GL initialization inside getContext() forever, which used to block every launch.
HOST_GPU_PROBE_TIMEOUT_S = 30.0

_READ_GPU = """() => {
    const gl = document.createElement('canvas').getContext('webgl');
    const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
    return info
        ? [gl.getParameter(info.UNMASKED_VENDOR_WEBGL), gl.getParameter(info.UNMASKED_RENDERER_WEBGL)]
        : null;
}"""


def add_canvas_placeholder(prefs: Dict[str, Any]) -> None:
    """Turn on the canvas placeholder, keeping any baseline overrides already set."""
    overrides = [o for o in str(prefs.get(BASELINE_OVERRIDES_PREF) or '').split(',') if o]
    prefs[BASELINE_OVERRIDES_PREF] = ','.join(overrides + list(CANVAS_PLACEHOLDER_TARGETS))


def has_canvas_placeholder(prefs: Mapping[str, Any]) -> bool:
    return CANVAS_PLACEHOLDER_TARGETS[0] in str(prefs.get(BASELINE_OVERRIDES_PREF) or '')


def set_webgpu(prefs: Dict[str, Any], target_os: str, gpu: Gpu, host: Optional[Gpu]) -> None:
    """Expose navigator.gpu where Firefox on the claimed device has it, with the
    host's adapter only when `gpu` is the host's hardware GPU.

    Firefox enables WebGPU on Windows and on Apple Silicon Macs only
    (dom.webgpu.enabled in StaticPrefList.yaml). Any other adapter would
    contradict the claimed GPU, so requestAdapter() returns null, as Windows
    Firefox does on the Microsoft Basic Render Driver. The status is written
    either way, because a persistent profile saves it and the next startup
    reads it. Prefs the caller set are kept.
    """
    enabled = prefs.setdefault('dom.webgpu.enabled', target_os == 'win' or (target_os == 'mac' and gpu[0] == 'Apple'))
    if enabled:
        own_adapter = renders_on_hardware(host) and gpu == host
        prefs.setdefault(WEBGPU_BLOCKLIST_PREF, FEATURE_STATUS_OK if own_adapter else FEATURE_BLOCKED_DEVICE)


def host_gpu(
    executable_path: str, headless: bool, env: Mapping[str, Any], prefs: Mapping[str, Any]
) -> Optional[Gpu]:
    """The (vendor, renderer) this machine's Firefox reports, or None without WebGL.

    Read from the binary about to launch, with no identity applied, under the
    same display and the same rendering prefs: headless, Xvfb, a GPU display
    and a real display can each render on a different device. The strings are
    the ones Firefox sanitizes itself.
    """
    return _host_gpu(
        str(executable_path),
        bool(headless),
        tuple(sorted((k, str(v)) for k, v in env.items() if not k.startswith(_LAUNCHER_ENV))),
        tuple(sorted((k, prefs[k]) for k in GPU_PREFS if k in prefs)),
    )


@lru_cache(maxsize=None)
def _host_gpu(
    executable_path: str,
    headless: bool,
    env: Tuple[Tuple[str, str], ...],
    prefs: Tuple[Tuple[str, Any], ...],
) -> Optional[Gpu]:
    # The probe runs in its own interpreter: the sync API refuses to start
    # inside a running asyncio loop, which is where AsyncCamoufox calls
    # launch_options from, and a hung probe has to be stoppable, which a thread
    # is not. Terminating the child closes its pipe to the Playwright driver,
    # which then shuts the browser down. PYTHONPATH makes the child import this
    # same package.
    child_env = dict(os.environ)
    child_env['PYTHONPATH'] = os.pathsep.join(
        filter(None, (str(Path(__file__).resolve().parent.parent), child_env.get('PYTHONPATH')))
    )
    child = subprocess.Popen(
        [sys.executable, '-m', 'camoufox.host_rendering'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
        text=True,
    )
    request = json.dumps(
        {'executable_path': executable_path, 'headless': headless, 'env': dict(env), 'prefs': dict(prefs)}
    )
    try:
        out, err = child.communicate(request, timeout=HOST_GPU_PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        child.terminate()
        child.communicate()
        display = dict(env).get('DISPLAY')
        context = f' (DISPLAY={display})' if display else ''
        raise TimeoutError(
            f'Host GPU probe timed out after {HOST_GPU_PROBE_TIMEOUT_S:g} s '
            f'while launching {executable_path}{context}. The browser did not '
            'answer the WebGL probe; check that the display accepts X connections.'
        ) from None
    if child.returncode != 0:
        raise RuntimeError(f'Host GPU probe failed while launching {executable_path}:\n{err.strip()}')
    gpu = json.loads(out)
    return (gpu[0], gpu[1]) if gpu else None


def _read_host_gpu(
    executable_path: str,
    headless: bool,
    env: Dict[str, str],
    prefs: Dict[str, Any],
) -> Optional[List[str]]:
    """Launch the binary once and read its WebGL vendor and renderer."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(
            executable_path=executable_path,
            headless=headless,
            env=env,
            # The launch forces WebGL on, which can choose another device.
            firefox_user_prefs={**prefs, 'webgl.force-enabled': True},
        )
        try:
            return browser.new_page().evaluate(_READ_GPU)
        finally:
            browser.close()


def renders_on_hardware(gpu: Optional[Gpu]) -> bool:
    """Whether the host's canvas and WebGL come from a GPU, not a software rasterizer."""
    return gpu is not None and not is_software_renderer(gpu[1])


if __name__ == '__main__':
    # _host_gpu's child: reads its request from stdin, writes the GPU as JSON.
    request = json.load(sys.stdin)
    json.dump(_read_host_gpu(**request), sys.stdout)
