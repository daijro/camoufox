import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from random import choice, randint, randrange, random, sample, shuffle
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from browserforge.fingerprints import (
    Fingerprint,
    FingerprintGenerator,
    ScreenFingerprint,
)

from camoufox.pkgman import load_yaml
from camoufox.webgl import sample_webgl

# Load the browserforge.yaml file
BROWSERFORGE_DATA = load_yaml('browserforge.yml')

FP_GENERATOR = FingerprintGenerator(browser='firefox', os=('linux', 'macos', 'windows'))

# Bundled real fingerprint presets
PRESETS_FILE = Path(__file__).parent / 'fingerprint-presets.json'
PRESETS_V150_FILE = Path(__file__).parent / 'fingerprint-presets-v150.json'
# Firefox major version at which the v150 preset bundle becomes preferred.
PRESETS_V150_MIN_FF = 149
_PRESETS_CACHE: Dict[Path, Dict] = {}

# CreepJS OS marker fonts used for OS detection
_MACOS_MARKER_FONTS = [
    'Helvetica Neue', 'PingFang HK', 'PingFang SC', 'PingFang TC',
]
_LINUX_MARKER_FONTS = [
    'Arimo', 'Cousine', 'Tinos', 'Twemoji Mozilla',
]
_WINDOWS_MARKER_FONTS = [
    'Segoe UI', 'Tahoma', 'Cambria Math', 'Nirmala UI',
]


def _ensure_marker_fonts(fonts: List[str], markers: List[str]) -> None:
    """Add any missing marker fonts to the font list (in-place)."""
    existing = set(fonts)
    for m in markers:
        if m not in existing:
            fonts.append(m)


# OS font lists loaded from fonts.json
_OS_FONTS_CACHE: Optional[Dict[str, List[str]]] = None

def _load_os_fonts() -> Dict[str, List[str]]:
    """Load the full OS font lists from fonts.json."""
    global _OS_FONTS_CACHE
    if _OS_FONTS_CACHE is not None:
        return _OS_FONTS_CACHE
    fonts_path = os.path.join(os.path.dirname(__file__), 'fonts.json')
    with open(fonts_path, 'rb') as f:
        import orjson
        _OS_FONTS_CACHE = orjson.loads(f.read())
    return _OS_FONTS_CACHE


# Essential fonts per OS that must always be included in subsets
_ESSENTIAL_FONTS_MACOS = [
    'Arial', 'Helvetica', 'Times New Roman', 'Courier New', 'Verdana',
    'Georgia', 'Trebuchet MS', 'Tahoma', 'Helvetica Neue', 'Lucida Grande',
    'Menlo', 'Monaco', 'Geneva', 'PingFang HK', 'PingFang SC', 'PingFang TC',
]
_ESSENTIAL_FONTS_WINDOWS = [
    'Arial', 'Times New Roman', 'Courier New', 'Verdana', 'Georgia',
    'Trebuchet MS', 'Tahoma', 'Segoe UI', 'Calibri', 'Cambria Math',
    'Nirmala UI', 'Consolas',
]
_ESSENTIAL_FONTS_LINUX = [
    'Arimo', 'Cousine', 'Tinos', 'Twemoji Mozilla',
    'Noto Sans Devanagari', 'Noto Sans JP', 'Noto Sans KR',
    'Noto Sans SC', 'Noto Sans TC',
]


def _generate_random_font_subset(target_os: str) -> List[str]:
    """
    Generate a random subset of fonts for the given OS.
    Picks a random percentage between 30-78% of non-essential fonts,
    always includes essential + marker fonts.
    """
    os_fonts_data = _load_os_fonts()
    os_key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}.get(target_os, 'mac')
    full_list = os_fonts_data.get(os_key, os_fonts_data.get('mac', []))

    if target_os == 'windows':
        essential = set(_ESSENTIAL_FONTS_WINDOWS)
        markers = _WINDOWS_MARKER_FONTS
    elif target_os == 'linux':
        essential = set(_ESSENTIAL_FONTS_LINUX)
        markers = _LINUX_MARKER_FONTS
    else:
        essential = set(_ESSENTIAL_FONTS_MACOS)
        markers = _MACOS_MARKER_FONTS

    # Split into essential and non-essential
    result = [f for f in full_list if f in essential]
    non_essential = [f for f in full_list if f not in essential]

    # Random percentage between 30-78%
    pct = 30 + int(random() * 49)
    count = round((pct / 100) * len(non_essential))

    # Randomly select non-essential fonts
    if count < len(non_essential):
        selected = sample(non_essential, count)
    else:
        selected = non_essential
    result.extend(selected)

    # Ensure marker fonts are present
    _ensure_marker_fonts(result, markers)

    return result


# OS voice lists loaded from voices.json, parsed into "Name:lang:type" tuples.
_OS_VOICES_CACHE: Optional[Dict[str, List[Tuple[str, str, str]]]] = None


def _load_os_voices() -> Dict[str, List[Tuple[str, str, str]]]:
    """Load OS voice lists from voices.json as (name, lang, type) tuples.

    Each entry is "Name:lang:type" (type is "local" or "remote"). Voice names
    may contain parens/commas but not colons, so a last-two-colons split is
    safe.
    """
    global _OS_VOICES_CACHE
    if _OS_VOICES_CACHE is not None:
        return _OS_VOICES_CACHE
    voices_path = os.path.join(os.path.dirname(__file__), 'voices.json')
    with open(voices_path, 'rb') as f:
        import orjson
        raw = orjson.loads(f.read())
    _OS_VOICES_CACHE = {}
    for os_key, entries in raw.items():
        parsed: List[Tuple[str, str, str]] = []
        for entry in entries:
            last = entry.rfind(':')
            if last < 0:
                continue
            vtype = entry[last + 1:]
            before = entry[:last]
            langsep = before.rfind(':')
            if langsep < 0:
                continue
            lang = before[langsep + 1:]
            name = before[:langsep]
            if name and lang:
                parsed.append((name, lang, vtype))
        _OS_VOICES_CACHE[os_key] = parsed
    return _OS_VOICES_CACHE


# Essential speech voices per OS that must always be included in subsets
_ESSENTIAL_VOICES_MACOS = [
    'Samantha', 'Alex', 'Fred', 'Victoria', 'Karen', 'Daniel',
]
_ESSENTIAL_VOICES_WINDOWS = [
    'Microsoft David - English (United States)',
    'Microsoft Zira - English (United States)',
    'Microsoft Mark - English (United States)',
]

# Real Firefox speechSynthesis URI prefixes per backend.
#   macOS NSSpeechSynthesizer -> "urn:moz-tts:osx:<dotted-slug>"
#   Windows SAPI              -> "urn:moz-tts:sapi:<dotted-slug>"
#   Linux speech-dispatcher   -> "urn:moz-tts:speechd:<escaped-name>?<lang>"
_VOICE_URI_PREFIX = {
    'mac': 'urn:moz-tts:osx:',
    'win': 'urn:moz-tts:sapi:',
    'lin': 'urn:moz-tts:speechd:',
}


def _voice_uri_slug(name: str) -> str:
    """Stable dotted slug for mac/win URIs (shape-plausible, not catalog-exact)."""
    return re.sub(r'^\.|\.$', '', re.sub(r'[^a-z0-9]+', '.', name.lower()))


def _voice_uri(os_key: str, name: str, lang: str) -> str:
    """Build a voiceUri matching what real Firefox emits for the OS backend."""
    if os_key == 'lin':
        # Firefox's SpeechDispatcherService.cpp builds:
        #   "urn:moz-tts:speechd:" + NS_EscapeURL(name, OnlyNonASCII|Spaces) + "?" + lang
        # i.e. spaces -> %20 and non-ASCII bytes -> %XX, ASCII punctuation intact.
        escaped = []
        for ch in name:
            if ch == ' ':
                escaped.append('%20')
            elif ord(ch) <= 0x7F:
                escaped.append(ch)
            else:
                escaped.append(''.join(f'%{b:02X}' for b in ch.encode('utf-8')))
        return f"{_VOICE_URI_PREFIX['lin']}{''.join(escaped)}?{lang}"
    return f"{_VOICE_URI_PREFIX.get(os_key, '')}{_voice_uri_slug(name)}"


def _generate_random_voice_subset(
    target_os: str, locale: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Generate the speech voice list for the given OS as MaskConfig objects.

    Returns a list of {lang, name, voiceUri, isDefault, isLocalService} dicts,
    the shape MaskConfig::MVoices() requires (it silently drops any entry
    missing a field, so raw name strings would register nothing).

    Without this override, Firefox registers the HOST machine's
    speech-dispatcher / SAPI / NSSpeech voices, leaking the OS the wrapper
    actually runs on. We therefore emit a list for EVERY target OS:
      macOS:   essential voices + a random 40-80% of the rest.
      Windows: full SAPI set (subsetting a fixed list reads as suspicious).
      Linux:   full espeak-ng base-language set (~131 voices) as enumerated
               by speech-dispatcher — the fixed list a Linux Firefox exposes.
    """
    os_voices_data = _load_os_voices()
    os_key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}.get(target_os, 'mac')
    full_list = os_voices_data.get(os_key, [])

    if not full_list:
        return []

    if os_key in ('win', 'lin'):
        # Fixed lists across installs (SAPI / espeak-ng) — ship the whole set.
        selected = list(full_list)
    else:
        # macOS: essential voices + random 40-80% of the rest.
        essential = set(_ESSENTIAL_VOICES_MACOS)
        result = [v for v in full_list if v[0] in essential]
        non_essential = [v for v in full_list if v[0] not in essential]
        pct = 40 + int(random() * 41)  # 40-80%
        count = round((pct / 100) * len(non_essential))
        if count < len(non_essential):
            result.extend(sample(non_essential, count))
        else:
            result.extend(non_essential)
        selected = result

    voices: List[Dict[str, Any]] = [
        {
            'name': name,
            'lang': lang,
            'voiceUri': _voice_uri(os_key, name, lang),
            'isDefault': False,
            'isLocalService': vtype == 'local',
        }
        for (name, lang, vtype) in selected
    ]

    # Mark a default voice matching the spoofed locale prefix so it lines up
    # with Intl.DateTimeFormat().resolvedOptions().locale (CreepJS flags a
    # voiceLangMismatch otherwise).
    if voices:
        prefix = locale.split('-')[0].lower() if locale else 'en'
        idx = next(
            (i for i, v in enumerate(voices) if locale and v['lang'].lower() == locale.lower()),
            -1,
        )
        if idx < 0:
            idx = next(
                (i for i, v in enumerate(voices) if v['lang'].split('-')[0].lower() == prefix),
                -1,
            )
        if idx < 0:
            idx = 0
        voices[idx]['isDefault'] = True

    return voices


def _normalize_preset_voices(
    voices: Any, target_os: str
) -> List[Dict[str, Any]]:
    """Coerce a preset's `speechVoices` into MaskConfig voice objects.

    Presets historically store voices as "Name:lang:type" strings, which the
    C++ MaskConfig::MVoices() silently drops (it needs full objects). Convert
    them; pass through entries that are already objects.
    """
    os_key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}.get(target_os, 'mac')
    result: List[Dict[str, Any]] = []
    for entry in voices:
        if isinstance(entry, dict):
            result.append(entry)
            continue
        last = entry.rfind(':')
        if last < 0:
            continue
        vtype = entry[last + 1:]
        before = entry[:last]
        langsep = before.rfind(':')
        if langsep < 0:
            continue
        lang = before[langsep + 1:]
        name = before[:langsep]
        if not name or not lang:
            continue
        result.append(
            {
                'name': name,
                'lang': lang,
                'voiceUri': _voice_uri(os_key, name, lang),
                'isDefault': False,
                'isLocalService': vtype == 'local',
            }
        )
    if result and not any(v['isDefault'] for v in result):
        result[0]['isDefault'] = True
    return result


def fix_navigator_arch(config: Dict[str, Any], target_os: str) -> None:
    """Force navigator.platform AND navigator.oscpu to match the UA's arch.

    ~8% of Linux Firefox fingerprints in the BrowserForge pool report
    "Linux armv81" for platform/oscpu while the UA says "Linux x86_64". That
    arch mismatch is itself a CreepJS lie signal (CreepJS cross-checks oscpu,
    platform, and the UA arch). Mac/Windows pools are consistent and need no
    correction.
    """
    if target_os != 'lin':
        return
    ua = config.get('navigator.userAgent')
    if not ua:
        return
    target = ''
    if 'Linux x86_64' in ua:
        target = 'Linux x86_64'
    elif 'Linux i686' in ua:
        target = 'Linux i686'
    if not target:
        return
    if config.get('navigator.platform') != target:
        config['navigator.platform'] = target
    if config.get('navigator.oscpu') != target:
        config['navigator.oscpu'] = target


def fix_screen_no_taskbar(config: Dict[str, Any], target_os: str) -> None:
    """Ensure screen.availHeight < screen.height so CreepJS's noTaskbar flag
    (screen.height == availHeight and screen.width == availWidth) doesn't flip.

    Every desktop OS keeps some chrome visible (Mac menu bar ~25px, Win taskbar
    ~40px, Linux panel ~27px); the BrowserForge pool occasionally ships
    fingerprints with identical screen/avail values which leak as a headless
    tell. Also clamp window.outerHeight (and innerHeight) to the new avail so
    the window isn't taller than the available area.
    """
    sw = config.get('screen.width')
    sh = config.get('screen.height')
    aw = config.get('screen.availWidth')
    ah = config.get('screen.availHeight')
    if not (sw and sh and aw == sw and ah == sh):
        return
    taskbar = 40 if target_os == 'win' else 25 if target_os == 'mac' else 27
    new_avail = sh - taskbar
    config['screen.availHeight'] = new_avail
    oh = config.get('window.outerHeight')
    if oh and oh > new_avail:
        ih = config.get('window.innerHeight')
        chrome = oh - ih if ih else 0
        config['window.outerHeight'] = new_avail
        if ih:
            config['window.innerHeight'] = new_avail - chrome


def clamp_window_dimensions(config: Dict[str, Any]) -> None:
    """Enforce inner <= outer <= avail <= screen on BOTH axes.

    The browser faithfully reports whatever we inject, so a BrowserForge
    fingerprint that ships e.g. outerWidth > screen.width or innerWidth >
    outerWidth leaks as an impossible geometry. Shrink each level down to its
    container, preserving the chrome delta between outer and inner where
    possible. Complements fix_screen_no_taskbar (which only clamps height).
    """
    for axis in ('Width', 'Height'):
        screen = config.get(f'screen.{axis.lower()}')
        avail = config.get(f'screen.avail{axis}')
        outer = config.get(f'window.outer{axis}')
        inner = config.get(f'window.inner{axis}')

        # avail must not exceed screen
        if screen and avail and avail > screen:
            config[f'screen.avail{axis}'] = screen
        avail_clamped = config.get(f'screen.avail{axis}', screen)

        # outer must not exceed avail (or screen if avail is unknown)
        outer_cap = avail_clamped if avail_clamped is not None else screen
        if outer and outer_cap and outer > outer_cap:
            chrome = max(0, outer - inner) if inner else 0
            config[f'window.outer{axis}'] = outer_cap
            if inner:
                config[f'window.inner{axis}'] = max(1, outer_cap - chrome)

        # inner must not exceed outer
        outer_clamped = config.get(f'window.outer{axis}', outer)
        inner_now = config.get(f'window.inner{axis}')
        if inner_now and outer_clamped and inner_now > outer_clamped:
            config[f'window.inner{axis}'] = outer_clamped


def clamp_screen_to_display(
    config: Dict[str, Any],
    max_width: Optional[int],
    max_height: Optional[int],
) -> None:
    """Shrink screen.width/height down to the bounds of the real display.

    BrowserForge takes a Screen constraint but drops it silently whenever it
    filters the fingerprint pool too far: FingerprintGenerator.partial_csp
    swallows the resulting failure and deletes the constraint unless strict=True.
    So the bound from get_screen_cons() is best-effort only, and a 1366x768
    laptop routinely gets a 2560x1440 fingerprint. browser-init.patch resizes the
    real chrome window to window.outerWidth/outerHeight, so an unbounded value
    renders past the edge of the monitor (daijro/camoufox#499).

    Keeps the taskbar delta (screen - avail) intact so fix_screen_no_taskbar's
    invariant survives. Callers must run clamp_window_dimensions afterwards to
    cascade the new bounds down to avail/outer/inner.
    """
    for axis, cap in (('width', max_width), ('height', max_height)):
        screen = config.get(f'screen.{axis}')
        if not (screen and cap) or screen <= cap:
            continue
        avail_key = 'screen.availWidth' if axis == 'width' else 'screen.availHeight'
        avail = config.get(avail_key)
        config[f'screen.{axis}'] = cap
        if avail:
            config[avail_key] = max(1, cap - max(0, screen - avail))


def clamp_window_position(config: Dict[str, Any]) -> None:
    """Keep the window box inside the screen: 0 <= screenX/Y <= screen - outer.

    BrowserForge's screenX/screenY are consistent with the screen it generated
    them against, so clamp_screen_to_display invalidates them. A window
    positioned partly off its own reported screen is an impossible geometry.
    """
    for axis, pos_key in (('Width', 'window.screenX'), ('Height', 'window.screenY')):
        screen = config.get(f'screen.{axis.lower()}')
        outer = config.get(f'window.outer{axis}')
        pos = config.get(pos_key)
        if pos is None or not (screen and outer):
            continue
        config[pos_key] = max(0, min(pos, screen - outer))


def set_media_devices_defaults(config: Dict[str, Any]) -> None:
    """Spoof navigator.mediaDevices.enumerateDevices() so headless contexts
    expose a plausible device list.

    A real desktop browser without explicit mic permission reports one
    audioinput + one videoinput; an empty list is a headless tell. The patched
    MediaDevices::FilterExposedDevices reads mediaDevices:{enabled,micros,
    webcams,speakers}. Default to one of each input kind unless the caller
    already set any mediaDevices: key.
    """
    if any(k.startswith('mediaDevices:') for k in config):
        return
    config['mediaDevices:enabled'] = True
    config['mediaDevices:micros'] = 1
    config['mediaDevices:webcams'] = 1
    config['mediaDevices:speakers'] = 0


# -- WebGL <-> screen coherence (#729) ---------------------------------------
#
# BrowserForge picks navigator/screen; the GPU is drawn separately from
# webgl_data.db weighted only by OS. Nothing ties the two together, so the
# synthetic path can emit pairs no real machine ships -- a discrete GPU behind
# a 1024x600 netbook panel. Consistency checks (Pixelscan, Fingerprint.com)
# read that as masking even when every individual value is plausible alone.
#
# What can honestly be claimed here is narrow, because Firefox never reports
# the GPU it actually sees. dom/canvas/SanitizeRenderer.cpp collapses every
# renderer string into one of ~11 representative device buckets before a page
# sees it (prefs webgl.sanitize-unmasked-renderer and
# webgl.enable-renderer-query, both default true; resistFingerprinting
# replaces the value with "Mozilla" outright). That file's own header comment
# gives the flavour: `"GeForce RTX 3090" => "GeForce GTX 980"`. So every RTX,
# every Quadro M/P/V/T and every GeForce 900-7999 arrive as one string, while
# "Intel(R) UHD Graphics 620" and "Mesa Intel(R) Iris(R) Xe Graphics" both
# arrive as an "Intel(R) HD Graphics" spelling.
#
# Two consequences. Matching on raw model names -- RTX, Quadro, RX, UHD, Iris,
# Mesa Intel -- can never fire, because those are exactly the strings Gecko
# collapses away. And a bucket spanning a desktop RTX 4090 and a mobile GTX
# 1650 Max-Q carries no useful screen floor: 1366x768 laptops with discrete
# NVIDIA GPUs are ordinary hardware, not a tell.
#
# So the rule below holds only what is true of *every* part behind a bucket,
# and renderers are reduced to their bucket first (see _renderer_bucket) so
# the ANGLE, nouveau and /PCIe/SSE2 spellings of one GPU land on one rule
# instead of three different ones.

# Software rasterizers. A VM or headless host reports whatever resolution the
# window manager hands it, so no screen constrains them -- and the sampler
# must never come to *prefer* them, because a software renderer is a far
# stronger "this is a bot" signal than any GPU/screen mismatch.
_SOFTWARE_RENDERERS: Tuple[str, ...] = (
    'llvmpipe',
    'Microsoft Basic Render Driver',
    'SwiftShader',
    'Generic Renderer',
)

# Discrete NVIDIA, plus the AMD R5/R7/R9/RX/Vega bucket. Everything else in
# webgl_data.db reaches down into netbook territory and gets no floor at all:
# the "Intel(R) HD Graphics" bucket swallows the GMA 3150 netbook chipset,
# "Radeon HD 3200 Graphics" is Gecko's catch-all for a bare "AMD"/"Radeon"
# (the C-50/E-350 netbook APUs included), and Apple silicon drives arbitrary
# external monitors from a Mac mini or Mac Studio.
_DISCRETE_GPU_BUCKETS: FrozenSet[str] = frozenset(
    {
        'GeForce 8800 GTX',
        'GeForce GTX 480',
        'GeForce GTX 980',
        'Radeon R9 200 Series',
    }
)

# Discrete GPUs did not ship in netbooks, and netbook panels topped out at
# 1024x600. That is the whole of the claim.
#
# It is an area rather than a width x height pair because real panels do not
# dominate one another: 1280x800 and 1366x768 are both ordinary laptop
# screens, and a per-axis floor taken from either one rejects the other. A
# 1366x768 laptop with a discrete GPU is common hardware, not a tell.
_NETBOOK_MAX_PIXELS = 1024 * 600

# The three shapes SanitizeRenderer wraps a device bucket in.
_ANGLE_D3D_RE = re.compile(r'^ANGLE \([^,]*, (.*?) Direct3D.*\)$')
_ANGLE_VULKAN_RE = re.compile(r'^ANGLE \((.*)\) on Vulkan$')
_PCIE_SSE2_RE = re.compile(r'^(.*)/PCIe?/SSE2$')


def _renderer_bucket(renderer: str) -> str:
    """Reduce a reported renderer to Gecko's sanitized device bucket.

    "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or
    similar" (Windows), "NVIDIA GeForce GTX 980/PCIe/SSE2" (Linux proprietary
    driver) and "GeForce GTX 980, or similar" (nouveau, which loses the vendor
    prefix) are one GPU class in three spellings. Without this they land on
    three different rules, or none.
    """
    core = renderer.removesuffix(', or similar')
    match = _ANGLE_D3D_RE.match(core) or _ANGLE_VULKAN_RE.match(core)
    if match:
        core = match.group(1)
    match = _PCIE_SSE2_RE.match(core)
    if match:
        core = match.group(1)
    # SanitizeRenderer re-adds the "NVIDIA " prefix only when the raw string
    # carried it, so one bucket arrives both with and without it.
    return core.removeprefix('NVIDIA ')


# The smallest screen mainstream hardware still ships. BrowserForge's pool
# carries netbook-era geometry that essentially no 2026 device reports, and
# that is a tell on its own, whatever GPU sits behind it.
MODERN_SCREEN_FLOOR: Tuple[int, int] = (1366, 768)


def raise_screen_to_modern_floor(config: Dict[str, Any]) -> None:
    """Lift netbook-era screen geometry to something current hardware reports.

    BrowserForge still draws 1024x600 and friends. Those panels left
    production a decade and a half ago, so the screen is what has to move --
    no GPU choice makes that profile look current.

    Keeps the screen-to-avail gap intact so fix_screen_no_taskbar's invariant
    survives; the window box is reconciled by clamp_window_dimensions and
    clamp_window_position, which run after this. Call BEFORE
    clamp_screen_to_display so a genuinely small real monitor still wins.
    """
    min_w, min_h = MODERN_SCREEN_FLOOR
    sw = config.get('screen.width')
    sh = config.get('screen.height')
    if not (sw and sh) or (sw >= min_w and sh >= min_h):
        return

    # Measure the gaps before mutating, or they get folded into themselves.
    aw = config.get('screen.availWidth')
    ah = config.get('screen.availHeight')
    gap_w = sw - aw if aw else None
    gap_h = sh - ah if ah else None

    new_w, new_h = max(sw, min_w), max(sh, min_h)
    config['screen.width'] = new_w
    config['screen.height'] = new_h
    if gap_w is not None:
        config['screen.availWidth'] = max(1, new_w - max(0, gap_w))
    if gap_h is not None:
        config['screen.availHeight'] = max(1, new_h - max(0, gap_h))


def is_software_renderer(renderer: Optional[str]) -> bool:
    """Whether `renderer` is a software rasterizer rather than real hardware."""
    return bool(renderer) and any(name in renderer for name in _SOFTWARE_RENDERERS)


def gpu_screen_is_plausible(
    renderer: Optional[str], width: Optional[int], height: Optional[int]
) -> bool:
    """Whether `renderer` is a GPU that plausibly drives a `width` x `height` screen.

    Unconstrained buckets and software rasterizers pass. The set only names
    buckets whose floor holds for every part behind them, so anything absent
    from it is genuinely unconstrained rather than merely unrecognised.
    """
    if not renderer or not width or not height:
        return True
    if is_software_renderer(renderer):
        return True
    if _renderer_bucket(renderer) not in _DISCRETE_GPU_BUCKETS:
        return True
    return width * height > _NETBOOK_MAX_PIXELS


def sample_webgl_for_screen(
    target_os: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
    attempts: int = 32,
) -> Dict[str, str]:
    """Sample a WebGL profile that is coherent with the screen already chosen.

    Rejection sampling, so the GPU keeps webgl_data.db's real OS-weighted
    distribution -- we only drop draws that contradict the screen. The screen
    itself is left alone on purpose: it has already been reconciled with the
    real display and the window box (clamp_screen_to_display,
    fix_screen_no_taskbar, clamp_window_dimensions, clamp_window_position),
    and widening it here to flatter the GPU would push a headful window back
    off the monitor it is drawn on (#499).

    The first draw settles hardware-vs-software at the pool's natural rate and
    is never resampled once it lands on a rasterizer. Rejecting only hardware
    draws would renormalise the survivors onto llvmpipe / WARP / SwiftShader:
    on a small screen that turns a 1.5% software rate into a 40% one, trading
    a weak incoherence for the strongest VM/headless tell there is.

    Falls back to that first draw when the pool holds nothing coherent, so an
    unusual screen degrades to today's behaviour rather than raising.
    """
    first = sample_webgl(target_os)
    renderer = first.get('webGl:renderer')
    if is_software_renderer(renderer) or gpu_screen_is_plausible(renderer, width, height):
        return first

    for _ in range(attempts - 1):
        candidate = sample_webgl(target_os)
        renderer = candidate.get('webGl:renderer')
        # Skip rather than accept: the class was settled by the first draw.
        if is_software_renderer(renderer):
            continue
        if gpu_screen_is_plausible(renderer, width, height):
            return candidate
    return first


def _select_presets_file(ff_version: Optional[Any] = None) -> Path:
    """Pick the bundled-presets file appropriate for a given Firefox version.

    For Firefox >= PRESETS_V150_MIN_FF, prefer the v150 bundle (real
    fingerprints scraped from contemporary browsers); otherwise fall back to
    the original bundle.
    """
    try:
        major = int(str(ff_version).split('.', 1)[0]) if ff_version else 0
    except (ValueError, TypeError):
        major = 0
    if major >= PRESETS_V150_MIN_FF and PRESETS_V150_FILE.exists():
        return PRESETS_V150_FILE
    return PRESETS_FILE


def load_presets(ff_version: Optional[Any] = None) -> Optional[Dict]:
    """Load bundled fingerprint presets from JSON file."""
    path = _select_presets_file(ff_version)
    if path in _PRESETS_CACHE:
        return _PRESETS_CACHE[path]
    if not path.exists():
        return None
    with open(path) as f:
        _PRESETS_CACHE[path] = json.load(f)
    return _PRESETS_CACHE[path]


# Map OS names to preset keys
_OS_TO_PRESET_KEY = {
    'windows': 'windows',
    'macos': 'macos',
    'linux': 'linux',
    'win': 'windows',
    'mac': 'macos',
    'lin': 'linux',
}


def get_random_preset(
    os: Optional[str] = None,
    ff_version: Optional[Any] = None,
) -> Optional[Dict]:
    """
    Get a random preset for the given OS.
    Returns None if no presets are available.
    """
    presets = load_presets(ff_version)
    if not presets:
        return None

    all_os_keys = ['macos', 'windows', 'linux']

    if os:
        # Normalize OS name
        if isinstance(os, (list, tuple)):
            os_keys = [_OS_TO_PRESET_KEY.get(o, o) for o in os]
        else:
            os_keys = [_OS_TO_PRESET_KEY.get(os, os)]
    else:
        os_keys = all_os_keys

    # Collect all matching presets
    candidates: List[Dict] = []
    for key in os_keys:
        candidates.extend(presets.get('presets', {}).get(key, []))

    if not candidates:
        return None

    return choice(candidates)  # nosec


# Tokens that name the machine rather than the platform: Firefox leaves every one
# of them out of appVersion.
_APP_VERSION_DROPPED = ('Win64', 'x64', 'Mobile', 'Tablet')


def _app_version_from_user_agent(user_agent: str) -> Optional[str]:
    """The appVersion Firefox reports for a browser sending this user agent.

    "5.0 (<OS tokens>)": the parenthesised part of the UA without the
    architecture, the Gecko revision, or the Windows build number.
    """
    block = re.match(r'Mozilla/5\.0 \(([^)]*)\)', user_agent or '')
    if not block:
        return None
    kept = []
    for token in (part.strip() for part in block.group(1).split(';')):
        if (
            token.startswith('rv:')
            or token in _APP_VERSION_DROPPED
            or token.startswith('Linux ')
            or token.startswith('Intel Mac OS X')
        ):
            continue
        kept.append('Windows' if token.startswith('Windows') else token)
    return f"5.0 ({'; '.join(kept)})" if kept else None


def from_preset(preset: Dict, ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Convert a real fingerprint preset to CAMOU_CONFIG format.
    """
    config: Dict[str, Any] = {}

    nav = preset.get('navigator', {})
    if nav.get('userAgent'):
        ua = nav['userAgent']
        # Replace Firefox version in UA if ff_version is provided
        if ff_version:
            ua = re.sub(r'Firefox/\d+\.0', f'Firefox/{ff_version}.0', ua)
            ua = re.sub(r'rv:\d+\.0', f'rv:{ff_version}.0', ua)
        config['navigator.userAgent'] = ua
    if nav.get('platform'):
        config['navigator.platform'] = nav['platform']
    if nav.get('hardwareConcurrency'):
        config['navigator.hardwareConcurrency'] = nav['hardwareConcurrency']
    if nav.get('oscpu'):
        config['navigator.oscpu'] = nav['oscpu']
    elif nav.get('platform'):
        # Derive oscpu from platform when not explicitly in the preset
        plat = nav['platform']
        if plat == 'MacIntel':
            config['navigator.oscpu'] = 'Intel Mac OS X 10.15'
        elif plat == 'Win32':
            config['navigator.oscpu'] = 'Windows NT 10.0; Win64; x64'
        elif 'Linux' in plat or 'linux' in plat:
            config['navigator.oscpu'] = 'Linux x86_64'
    if nav.get('appVersion'):
        config['navigator.appVersion'] = nav['appVersion']
    elif config.get('navigator.userAgent'):
        # Left unset, appVersion falls through to the *host's* value and then
        # contradicts the userAgent and platform set above: a Linux preset on a
        # macOS host reported "5.0 (Macintosh)" beside platform "Linux x86_64",
        # which any page can read in two properties.
        #
        # Firefox builds it from the same OS tokens as the userAgent, minus the
        # architecture and rv, with Windows collapsed to its family name. Deriving
        # it from the UA rather than from the platform keeps the distro token that
        # 20 of the bundled Linux presets carry ("X11; Ubuntu"), which a platform
        # lookup would flatten to "X11" — a mismatch of the same kind, if a
        # smaller one. Checked against 800 browserforge fingerprints: exact every
        # time.
        derived = _app_version_from_user_agent(config['navigator.userAgent'])
        if derived:
            config['navigator.appVersion'] = derived
    if 'maxTouchPoints' in nav:
        config['navigator.maxTouchPoints'] = nav['maxTouchPoints']

    screen = preset.get('screen', {})
    if screen.get('width'):
        config['screen.width'] = screen['width']
    if screen.get('height'):
        config['screen.height'] = screen['height']
    if screen.get('colorDepth'):
        config['screen.colorDepth'] = screen['colorDepth']
        config['screen.pixelDepth'] = screen['colorDepth']
    if screen.get('availWidth'):
        config['screen.availWidth'] = screen['availWidth']
    if screen.get('availHeight'):
        config['screen.availHeight'] = screen['availHeight']

    webgl = preset.get('webgl', {})
    if webgl.get('unmaskedVendor'):
        config['webGl:vendor'] = webgl['unmaskedVendor']
    if webgl.get('unmaskedRenderer'):
        config['webGl:renderer'] = webgl['unmaskedRenderer']

    # Generate unique random seeds per launch (1 to 2^32-1, excluding 0 which is a no-op in C++)
    config['fonts:spacing_seed'] = randint(1, 4_294_967_295)  # nosec
    config['audio:seed'] = randint(1, 4_294_967_295)  # nosec
    config['canvas:seed'] = randint(1, 4_294_967_295)  # nosec

    if preset.get('timezone'):
        config['timezone'] = preset['timezone']

    # Generate a unique random font subset from the OS font list.
    plat = nav.get('platform', '')
    if plat == 'MacIntel':
        target_os = 'macos'
    elif plat == 'Win32':
        target_os = 'windows'
    elif 'Linux' in plat or 'linux' in plat:
        target_os = 'linux'
    else:
        target_os = 'macos'
    try:
        config['fonts'] = _generate_random_font_subset(target_os)
    except Exception:
        # Fallback to preset fonts if font generation fails
        if preset.get('fonts'):
            fonts = list(preset['fonts'])
            _ensure_marker_fonts(fonts, {
                'macos': _MACOS_MARKER_FONTS,
                'windows': _WINDOWS_MARKER_FONTS,
                'linux': _LINUX_MARKER_FONTS,
            }.get(target_os, _MACOS_MARKER_FONTS))
            config['fonts'] = fonts
    # Generate a unique random voice subset from the OS voice list
    try:
        config['voices'] = _generate_random_voice_subset(target_os)
    except Exception:
        if preset.get('speechVoices'):
            config['voices'] = _normalize_preset_voices(
                preset['speechVoices'], target_os
            )

    return config


def _build_init_script(values: Dict[str, Any]) -> str:
    """
    Builds the JavaScript init script that calls per-context window.setXxx() functions.
    These functions self-destruct after first call, so they must run via addInitScript.
    """
    import json as _json

    lines = ['(function(v) {', '  var w = window;']

    setters = [
        ('fontSpacingSeed', 'setFontSpacingSeed', '{val}'),
        ('audioFingerprintSeed', 'setAudioFingerprintSeed', '{val}'),
        ('canvasSeed', 'setCanvasSeed', '{val}'),
        ('navigatorPlatform', 'setNavigatorPlatform', '{val}'),
        ('navigatorOscpu', 'setNavigatorOscpu', '{val}'),
        ('navigatorUserAgent', 'setNavigatorUserAgent', '{val}'),
        ('hardwareConcurrency', 'setNavigatorHardwareConcurrency', '{val}'),
        ('webglVendor', 'setWebGLVendor', '{val}'),
        ('webglRenderer', 'setWebGLRenderer', '{val}'),
    ]

    for key, fn_name, _template in setters:
        val = values.get(key)
        if val is not None:
            js_val = _json.dumps(val)
            lines.append(
                f'  if (typeof w.{fn_name} === "function") w.{fn_name}({js_val});'
            )

    # Screen dimensions (requires width + height together)
    sw = values.get('screenWidth')
    sh = values.get('screenHeight')
    if sw and sh:
        lines.append(
            f'  if (typeof w.setScreenDimensions === "function") w.setScreenDimensions({sw}, {sh});'
        )
        scd = values.get('screenColorDepth')
        if scd:
            lines.append(
                f'  if (typeof w.setScreenColorDepth === "function") w.setScreenColorDepth({scd});'
            )

    # Timezone — only call setTimezone() when we have an explicit value.
    # Without this, the C++ MaskConfig fallback (from CAMOU_CONFIG set by geoip
    # in launch_options) handles timezone for both main thread and workers via
    # SetNewDocument() and TimezoneManager::GetTimezone().
    # The old fallback read system TZ and poisoned RoverfoxStorageManager,
    # preventing MaskConfig from ever being consulted.
    tz = values.get('timezone')
    if tz:
        lines.append(
            f'  if (typeof w.setTimezone === "function") w.setTimezone({_json.dumps(tz)});'
        )

    # WebRTC IP
    ip = values.get('webrtcIP')
    if ip:
        lines.append(
            f'  if (typeof w.setWebRTCIPv4 === "function") w.setWebRTCIPv4({_json.dumps(ip)});'
        )
    else:
        lines.append(
            '  if (typeof w.setWebRTCIPv4 === "function") w.setWebRTCIPv4("");'
        )

    # Font list (comma-separated)
    font_list = values.get('fontList')
    if font_list and len(font_list) > 0:
        joined = ','.join(font_list)
        lines.append(
            f'  if (typeof w.setFontList === "function") w.setFontList({_json.dumps(joined)});'
        )

    # Speech voices (comma-separated names). config['voices'] holds MaskConfig
    # voice objects; extract the display name from each (tolerating a legacy
    # list of plain name strings).
    voices = values.get('speechVoices')
    if voices and len(voices) > 0:
        names = [v['name'] if isinstance(v, dict) else v for v in voices]
        joined = ','.join(names)
        lines.append(
            f'  if (typeof w.setSpeechVoices === "function") w.setSpeechVoices({_json.dumps(joined)});'
        )

    lines.append('})();')
    return '\n'.join(lines)


def generate_context_fingerprint(
    preset: Optional[Dict] = None,
    os: Optional[str] = None,
    ff_version: Optional[str] = None,
    webrtc_ip: Optional[str] = None,
    timezone: Optional[str] = None,
    locale: Optional[str] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate fingerprint values for a single per-context identity.
    Returns a dict with init_script (JS string) and context_options (Playwright options).

    By default, uses BrowserForge for infinite unique synthetic fingerprints.
    Pass a preset dict to use a real fingerprint preset instead.

    Parameters:
        timezone: IANA timezone string (e.g. 'Europe/London'). When provided,
            injected into config before init_script generation. Takes priority
            over any timezone from the preset.
        locale: BCP-47 locale string (e.g. 'en-GB'). When provided, parsed via
            normalize_locale() and injected into config. Also sets
            context_options['locale'] for Playwright.
        config_overrides: Dict of CAMOU_CONFIG keys to override after config
            is built but before init_script is rendered. Useful for disabling
            perturbation (e.g. {'fonts:spacing_seed': 0}).
    """
    if preset is not None:
        # Use real fingerprint preset
        config = from_preset(preset, ff_version)
        nav = preset.get('navigator', {})
        screen = preset.get('screen', {})
        webgl = preset.get('webgl', {})
    else:
        # Fall back to BrowserForge synthetic generation
        fp = generate_fingerprint(os=os)
        config = from_browserforge(fp, ff_version)

        # Add seeds (BrowserForge doesn't generate these)
        config.setdefault('fonts:spacing_seed', randint(1, 4_294_967_295))  # nosec
        config.setdefault('audio:seed', randint(1, 4_294_967_295))  # nosec
        config.setdefault('canvas:seed', randint(1, 4_294_967_295))  # nosec

        # Determine target OS from platform for font/voice generation
        plat = config.get('navigator.platform', '')
        os_name = 'macos'
        if plat == 'Win32':
            os_name = 'windows'
        elif 'Linux' in plat or 'linux' in plat:
            os_name = 'linux'

        # Add fonts (BrowserForge doesn't generate these)
        if 'fonts' not in config:
            try:
                config['fonts'] = _generate_random_font_subset(os_name)
            except Exception:
                pass

        # Add voices (BrowserForge doesn't generate these)
        if 'voices' not in config:
            try:
                config['voices'] = _generate_random_voice_subset(os_name)
            except Exception:
                pass

        # Derive oscpu if BrowserForge didn't provide it
        if 'navigator.oscpu' not in config:
            plat = config.get('navigator.platform', '')
            if plat == 'MacIntel':
                config['navigator.oscpu'] = 'Intel Mac OS X 10.15'
            elif plat == 'Win32':
                config['navigator.oscpu'] = 'Windows NT 10.0; Win64; x64'
            elif 'Linux' in plat or 'linux' in plat:
                config['navigator.oscpu'] = 'Linux x86_64'

        # Sample WebGL vendor/renderer from database (BrowserForge doesn't generate these)
        if not config.get('webGl:vendor') or not config.get('webGl:renderer'):
            _os_map = {'macos': 'mac', 'linux': 'lin', 'windows': 'win'}
            _target_os = _os_map.get(os or '', None)
            if not _target_os:
                plat = config.get('navigator.platform', '')
                if plat == 'Win32':
                    _target_os = 'win'
                elif 'Linux' in plat or 'linux' in plat:
                    _target_os = 'lin'
                else:
                    _target_os = 'mac'
            try:
                # Same coherence treatment launch_options applies (#729): lift
                # netbook geometry, then keep the GPU consistent with whatever
                # screen this identity ended up with. This path has no real
                # display to reconcile against, so the floor is unconditional.
                raise_screen_to_modern_floor(config)
                webgl_fp = sample_webgl_for_screen(
                    _target_os, config.get('screen.width'), config.get('screen.height')
                )
                webgl_fp.pop('webGl2Enabled', None)
                config.update(webgl_fp)
            except Exception:
                pass

        # Build source dicts from BrowserForge config for init_values
        nav = {
            'platform': config.get('navigator.platform'),
            'hardwareConcurrency': config.get('navigator.hardwareConcurrency'),
        }
        screen = {
            'width': config.get('screen.width'),
            'height': config.get('screen.height'),
            'colorDepth': config.get('screen.colorDepth'),
            'devicePixelRatio': None,
        }
        webgl = {
            'unmaskedVendor': config.get('webGl:vendor'),
            'unmaskedRenderer': config.get('webGl:renderer'),
        }
        preset = {'navigator': nav, 'screen': screen, 'webgl': webgl}

    # Inject explicit timezone/locale into config (takes priority over preset)
    if timezone:
        config['timezone'] = timezone
    if locale:
        from .locales import normalize_locale
        parsed = normalize_locale(locale)
        config['locale:language'] = parsed.language
        config['locale:region'] = parsed.region
        config['navigator.language'] = parsed.as_string
        if parsed.script:
            config['locale:script'] = parsed.script

    # Apply caller overrides before rendering init_script
    if config_overrides:
        config.update(config_overrides)

    # Build the values dict for the init script (works for both paths)
    init_values: Dict[str, Any] = {
        'fontSpacingSeed': config.get('fonts:spacing_seed'),
        'audioFingerprintSeed': config.get('audio:seed'),
        'canvasSeed': config.get('canvas:seed'),
        'navigatorPlatform': nav.get('platform'),
        'navigatorOscpu': config.get('navigator.oscpu'),
        'navigatorUserAgent': config.get('navigator.userAgent'),
        'hardwareConcurrency': nav.get('hardwareConcurrency') or config.get('navigator.hardwareConcurrency'),
        'webglVendor': webgl.get('unmaskedVendor'),
        'webglRenderer': webgl.get('unmaskedRenderer'),
        'screenWidth': screen.get('width'),
        'screenHeight': screen.get('height'),
        'screenColorDepth': screen.get('colorDepth'),
        'timezone': preset.get('timezone') if isinstance(preset.get('timezone'), str) else config.get('timezone'),
        'fontList': config.get('fonts'),
        'speechVoices': config.get('voices'),
        'webrtcIP': webrtc_ip or '',
    }

    init_script = _build_init_script(init_values)

    # Playwright context options that must be set at context creation
    context_options: Dict[str, Any] = {}
    ua = config.get('navigator.userAgent')
    if ua:
        context_options['user_agent'] = ua
    sw = screen.get('width')
    sh = screen.get('height')
    if sw and sh:
        context_options['viewport'] = {
            'width': sw,
            'height': max(sh - 28, 600),
        }
    dpr = screen.get('devicePixelRatio')
    if dpr:
        context_options['device_scale_factor'] = dpr
    tz = config.get('timezone')
    if not tz and isinstance(preset, dict):
        tz = preset.get('timezone')
    if tz:
        context_options['timezone_id'] = tz
    nav_lang = config.get('navigator.language')
    if nav_lang:
        context_options['locale'] = nav_lang

    return {
        'init_script': init_script,
        'context_options': context_options,
        'config': config,
        'preset': preset,
    }


@dataclass
class ExtendedScreen(ScreenFingerprint):
    """
    An extended version of Browserforge's ScreenFingerprint class
    """

    screenY: Optional[int] = None


def _cast_to_properties(
    camoufox_data: Dict[str, Any],
    cast_enum: Dict[str, Any],
    bf_dict: Dict[str, Any],
    ff_version: Optional[str] = None,
) -> None:
    """
    Casts Browserforge fingerprints to Camoufox config properties.
    """
    for key, data in bf_dict.items():
        # Ignore non-truthy values
        if not data:
            continue
        # Get the associated Camoufox property
        type_key = cast_enum.get(key)
        if not type_key:
            continue
        # If the value is a dictionary, recursively recall
        if isinstance(data, dict):
            _cast_to_properties(camoufox_data, type_key, data, ff_version)
            continue
        # Fix values that are out of bounds
        if type_key.startswith("screen.") and isinstance(data, int) and data < 0:
            data = 0
        # Replace the Firefox versions with ff_version
        if ff_version and isinstance(data, str):
            data = re.sub(r'(?<!\d)(1[0-9]{2})(\.0)(?!\d)', rf'{ff_version}\2', data)
        camoufox_data[type_key] = data


def handle_screenXY(camoufox_data: Dict[str, Any], fp_screen: ScreenFingerprint) -> None:
    """
    Helper method to set window.screenY based on Browserforge's screenX value.
    """
    # Skip if manually provided
    if 'window.screenY' in camoufox_data:
        return
    # Default screenX to 0 if not provided
    screenX = fp_screen.screenX
    if not screenX:
        camoufox_data['window.screenX'] = 0
        camoufox_data['window.screenY'] = 0
        return

    # If screenX is within [-50, 50], use the same value for screenY
    if screenX in range(-50, 51):
        camoufox_data['window.screenY'] = screenX
        return

    # Browserforge thinks the browser is windowed. # Randomly generate a screenY value.
    screenY = fp_screen.availHeight - fp_screen.outerHeight
    if screenY == 0:
        camoufox_data['window.screenY'] = 0
    elif screenY > 0:
        camoufox_data['window.screenY'] = randrange(0, screenY)  # nosec
    else:
        camoufox_data['window.screenY'] = randrange(screenY, 0)  # nosec


def from_browserforge(fingerprint: Fingerprint, ff_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Converts a Browserforge fingerprint to a Camoufox config.
    """
    camoufox_data: Dict[str, Any] = {}
    _cast_to_properties(
        camoufox_data,
        cast_enum=BROWSERFORGE_DATA,
        bf_dict=asdict(fingerprint),
        ff_version=ff_version,
    )
    handle_screenXY(camoufox_data, fingerprint.screen)

    return camoufox_data


def handle_window_size(fp: Fingerprint, outer_width: int, outer_height: int) -> None:
    """
    Helper method to set a custom outer window size, and center it in the screen
    """
    # Cast the screen to an ExtendedScreen
    fp.screen = ExtendedScreen(**asdict(fp.screen))
    sc = fp.screen

    # Center the window on the screen
    sc.screenX += (sc.width - outer_width) // 2
    sc.screenY = (sc.height - outer_height) // 2

    # Update inner dimensions if set
    if sc.innerWidth:
        sc.innerWidth = max(outer_width - sc.outerWidth + sc.innerWidth, 0)
    if sc.innerHeight:
        sc.innerHeight = max(outer_height - sc.outerHeight + sc.innerHeight, 0)

    # Set outer dimensions
    sc.outerWidth = outer_width
    sc.outerHeight = outer_height


def generate_fingerprint(window: Optional[Tuple[int, int]] = None, **config) -> Fingerprint:
    """
    Generates a Firefox fingerprint with Browserforge.
    """
    if window:  # User-specified outer window size
        fingerprint = FP_GENERATOR.generate(**config)
        handle_window_size(fingerprint, *window)
        return fingerprint
    return FP_GENERATOR.generate(**config)


if __name__ == "__main__":
    from pprint import pprint

    fp = generate_fingerprint()
    pprint(from_browserforge(fp))
