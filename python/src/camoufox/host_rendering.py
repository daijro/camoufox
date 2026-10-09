"""What this machine renders, and covering it when the identity claims another OS.

A page can draw a canvas or a WebGL scene and read the pixels back, and those
pixels come from the real OS, driver and GPU whatever the identity claims. On
the host's own OS the identity claims the GPU the host renders with, so the
pixels agree with it. An identity on another OS cannot agree, so its canvas
readback is replaced with random data, as privacy.resistFingerprinting does in
LibreWolf, Tor Browser and Mullvad Browser. Stock Firefox does not do that.
WebGPU hands the page the host's adapter, so the identity gets it only when it
claims the host's GPU.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional, Tuple

from .fingerprints import is_software_renderer

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


def host_gpu(executable_path: str, headless: bool, env: Mapping[str, Any]) -> Optional[Gpu]:
    """The (vendor, renderer) this machine's Firefox reports, or None without WebGL.

    Read from the binary about to launch, with no identity applied, under the
    same display: headless, Xvfb and a real display can each render on a
    different device. The strings are the ones Firefox sanitizes itself.
    """
    return _host_gpu(
        str(executable_path),
        bool(headless),
        tuple(sorted((k, str(v)) for k, v in env.items() if not k.startswith(_LAUNCHER_ENV))),
    )


@lru_cache(maxsize=None)
def _host_gpu(executable_path: str, headless: bool, env: Tuple[Tuple[str, str], ...]) -> Optional[Gpu]:
    def read() -> Optional[Gpu]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.firefox.launch(
                executable_path=executable_path,
                headless=headless,
                env=dict(env),
                # The launch forces WebGL on, which can choose another device.
                firefox_user_prefs={'webgl.force-enabled': True},
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
