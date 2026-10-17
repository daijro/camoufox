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

import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional, Tuple

from .fingerprints import is_software_renderer
from .pkgman import LAUNCHER_CONSTANTS

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

# GPUAdapter.limits of stock Firefox 152.0.4 on Windows (wgpu's D3D12 backend),
# measured 2026-09-24 on an RTX 4090. The same GPU driven from a Linux host
# reports 14 of them differently (maxBindingsPerBindGroup 1000000,
# minUniformBufferOffsetAlignment 32, ...), each one property read away;
# webgpu-limits-spoofing.patch reports these instead (webGpu:limits).
WINDOWS_WEBGPU_LIMITS: Dict[str, int] = LAUNCHER_CONSTANTS['windowsWebGpuLimits']

# Firefox reports the renderer through SanitizeRenderer.cpp, which keeps a
# vendor only for strings it recognises: Mesa's d3d12 driver under WSL says
# "D3D12 (NVIDIA GeForce RTX 4090)", and Firefox reports "Generic Renderer"
# for it. With the pref off it reports the driver's own string.
SANITIZE_RENDERER_PREF = 'webgl.sanitize-unmasked-renderer'

# The GPU vendors a renderer or vendor string can name, as Firefox reports them
# on each OS ("ANGLE (NVIDIA, ...)", "GeForce GTX 980, or similar", "Intel
# Inc.", "ATI Technologies Inc.") and as drivers do ("D3D12 (AMD Radeon RX
# 6800)", "Mesa Intel(R) UHD Graphics 620 (KBL GT2)").
_GPU_FAMILIES = (
    ('NVIDIA', re.compile(r'NVIDIA|GeForce|Quadro|nouveau')),
    ('AMD', re.compile(r'\bAMD\b|\bATI\b|Radeon|FirePro|Advanced Micro Devices')),
    ('Intel', re.compile(r'Intel')),
    ('Apple', re.compile(r'\bApple\b')),
)

# What the launcher itself adds to the browser's environment; none of it
# changes which device Firefox renders on.
_LAUNCHER_ENV = ('CAMOU_', 'FONTCONFIG_FILE')

Gpu = Tuple[str, str]

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


def set_webgpu(
    prefs: Dict[str, Any], target_os: str, gpu: Gpu, host: Optional[Gpu], passthrough: bool = False
) -> None:
    """Expose navigator.gpu where Firefox on the claimed device has it, with the
    host's adapter only when `gpu` is the host's hardware GPU, or when the
    launch passes the host's GPU through (gpu_passthrough).

    Firefox enables WebGPU on Windows and on Apple Silicon Macs only
    (dom.webgpu.enabled in StaticPrefList.yaml). Any other adapter would
    contradict the claimed GPU, so requestAdapter() returns null, as Windows
    Firefox does on the Microsoft Basic Render Driver. The status is written
    either way, because a persistent profile saves it and the next startup
    reads it. Prefs the caller set are kept.
    """
    enabled = prefs.setdefault('dom.webgpu.enabled', target_os == 'win' or (target_os == 'mac' and gpu[0] == 'Apple'))
    if enabled:
        own_adapter = passthrough or (renders_on_hardware(host) and gpu == host)
        prefs.setdefault(WEBGPU_BLOCKLIST_PREF, FEATURE_STATUS_OK if own_adapter else FEATURE_BLOCKED_DEVICE)


def host_gpu(executable_path: str, headless: bool, env: Mapping[str, Any], raw: bool = False) -> Optional[Gpu]:
    """The (vendor, renderer) this machine's Firefox reports, or None without WebGL.

    Read from the binary about to launch, with no identity applied, under the
    same display: headless, Xvfb and a real display can each render on a
    different device. The strings are the ones Firefox sanitizes itself, or
    with `raw` the driver's own renderer string (SANITIZE_RENDERER_PREF).
    """
    return _host_gpu(
        str(executable_path),
        bool(headless),
        tuple(sorted((k, str(v)) for k, v in env.items() if not k.startswith(_LAUNCHER_ENV))),
        bool(raw),
    )


@lru_cache(maxsize=None)
def _host_gpu(executable_path: str, headless: bool, env: Tuple[Tuple[str, str], ...], raw: bool = False) -> Optional[Gpu]:
    def read() -> Optional[Gpu]:
        from playwright.sync_api import sync_playwright

        prefs: Dict[str, Any] = {'webgl.force-enabled': True}
        if raw:
            prefs[SANITIZE_RENDERER_PREF] = False
        with sync_playwright() as playwright:
            browser = playwright.firefox.launch(
                executable_path=executable_path,
                headless=headless,
                env=dict(env),
                # The launch forces WebGL on, which can choose another device.
                firefox_user_prefs=prefs,
            )
            try:
                gpu = browser.new_page().evaluate(_READ_GPU)
            finally:
                browser.close()
        return (gpu[0], gpu[1]) if gpu else None

    # The sync API refuses to start inside a running asyncio loop, which is
    # where AsyncCamoufox calls launch_options from.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(read).result()


def renders_on_hardware(gpu: Optional[Gpu]) -> bool:
    """Whether the host's canvas and WebGL come from a GPU, not a software rasterizer.

    A host that renders in software matches any GPU on its own OS: it reads as
    a machine whose driver failed to load.
    """
    return gpu is not None and not is_software_renderer(gpu[1])


def gpu_family(gpu: Gpu) -> Optional[str]:
    """The vendor that made `gpu` (NVIDIA, AMD, Intel or Apple), or None.

    The renderer names the device and is read first: Linux Firefox can report
    an NVIDIA or AMD GPU under the "Mesa" vendor, and Mesa's d3d12 driver
    reports every GPU under "Microsoft Corporation". The first vendor the
    renderer names wins, as in "ANGLE (Intel, Intel(R) HD Graphics ...)".
    """
    for text in (gpu[1], gpu[0]):
        named = [(match.start(), family) for family, pattern in _GPU_FAMILIES if (match := pattern.search(text or ''))]
        if named:
            return min(named)[1]
    return None
