"""Whole-identity coherence: the checks that look at more than one field.

Camoufox assembles an identity from several pools -- the navigator and screen
from the fingerprint generator, the GPU from fpgen's WebGL records, fonts and
voices from its own catalogues, media devices from `media-devices.json`. Each
pool is sampled on its own, so a combination that no machine has ever had can be built
out of individually plausible parts: an Apple M1 with 2 cores, an Intel Mac GPU
behind a notched Apple Silicon panel, a Linux identity whose platform says
armv81 while its user agent says x86_64.

That class of defect cannot be removed by cleaning the pools, because it is
created when they are combined. So every identity passes through here, whatever
it was built from: a generated fingerprint, a bundled preset, or a config the
caller wrote by hand.

Each rule states an invariant that holds on real machines, says how to repair an
identity that breaks it where a correct value is determined, and is checked
again afterwards. `validate()` reports what is still broken; `apply()` repairs
what it can. Rules are written against measured behaviour, and the measurement
is cited in the rule -- a rule nobody can trace is a rule nobody can revise.

Ground truth used below was captured from stock Firefox 152.0.4, headed, on
three machines on 2026-09-17: a 16-core Linux box (1920x1080, colorDepth 24,
dpr 1, "Radeon HD 3200 Graphics, or similar"), a 16-core Windows 11 laptop with
a touchscreen (3456x2160 at dpr 2.5 -> 1382x864 CSS, colorDepth 24, maxTouchPoints
5, ANGLE/Intel), and a 10-core Apple Silicon Mac mini (2560x1440, colorDepth 30,
dpr 2, "Apple M1, or similar" -- the machine is an M4, and Firefox generalises
the renderer string itself).
"""

from typing import AbstractSet, Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from .pkgman import LAUNCHER_CONSTANTS

# Core counts Apple Silicon actually ships. The M1 is the floor at 8; nothing
# Apple has made has fewer. Firefox reports "Apple M1, or similar" for every
# M-series part, so the renderer string cannot narrow it further than this.
# 11 is in the set because the M3 Pro is 6P+5E -- an odd count that is real, and
# the reason this is an explicit list rather than "8 to 32": 9, 13 and 15 are
# not Apple parts. Apple Silicon has no SMT, so logical cores == physical.
APPLE_SILICON_CORES = frozenset(LAUNCHER_CONSTANTS['appleSiliconCores'])

# devicePixelRatio by platform. Windows exposes the display-scaling steps
# (100/125/150/175/200/250/300%); macOS reports 1 or 2 and nothing between;
# Linux reports 1, or 2 under HiDPI, with GNOME fractional scaling giving the
# 1.25/1.5/1.75 steps. Values outside these (1.818, 1.09, 1.36) are scraped
# artefacts -- a browser zoom level folded into the ratio, not a display mode.
#
# Ascending tuples, not sets: the repair keeps the first of two equally near
# steps, and a frozenset literal iterates in a different order when compiled
# than when loaded from a .pyc -- so a set made the first launch repair an
# identity differently from every later one.
PLAUSIBLE_DPR = {os_key: tuple(steps) for os_key, steps in LAUNCHER_CONSTANTS['plausibleDpr'].items()}

# colorDepth: Firefox reports 24, or 30 on a deep-colour display. macOS defaults
# to deep colour, so a Mac reports 30: measured on an M4 Mac mini and an M1 Pro
# MacBook, and 30 in every Apple Silicon preset and all but one Intel Mac one.
# 32 appears in scraped data and is not a value Firefox emits.
PLAUSIBLE_COLOR_DEPTH = frozenset({24, 30})

# maxTouchPoints: 0 with no digitiser, otherwise the panel's maximum simultaneous
# contacts. Measured 5 on the Windows laptop. This is a RANGE rather than a list
# of seen values, because neither source is authoritative here: fpgen's Windows
# pool offers 0, 1 and 10 and never the 5 the real machine reports, while the
# presets carry 40 and fpgen's draws carry 256. Consumer digitisers top out at
# 10 contacts; anything above that is a scraped artefact.
MAX_PLAUSIBLE_TOUCH_POINTS = 10

# The browser's own chrome height, in CSS pixels: the toolbar strip above the
# content area. Measured 86 on this build (stock Firefox's own value; see the
# leak register's chrome-height row), and it is a property of the BINARY, not of
# the identity -- the same window furniture renders whatever OS is claimed.
#
# It matters because the real window is sized from window.outerHeight, so the
# content area a page can actually receive input in is outerHeight - 86. An
# identity claiming `outerHeight - innerHeight` SMALLER than that is claiming a
# viewport taller than the window can hold, and the difference is unreachable:
# mouse events dispatched into those bottom rows are delivered to nothing.
# Measured 2026-09-17 -- a drawn pair of outer 801 / inner 717 (chrome 84) left
# the bottom 2 rows dead, which the boundary-sweep guard caught.
BROWSER_CHROME_HEIGHT = 86

# GPU strings that are not possible on macOS. Firefox 152 renders WebGL on a Mac
# through CGL, not ANGLE: its SanitizeRenderer has no ANGLE-on-Metal branch
# (Bug 2046027 added one after 152).
#
# Every other string a Mac reports is a bucket, not a device. SanitizeRenderer
# maps an Intel Mac's UHD 630 or Iris Plus 655 to "Intel(R) HD Graphics 400" and
# a Radeon Pro 5300M to "Radeon R9 200 Series" (Firefox's TestCiMac and
# TestMacAmd cases), so neither belongs here.
_NOT_A_MAC_GPU = ('ANGLE', 'llvmpipe')

# navigator.hardwareConcurrency on an Intel Mac. Firefox reports the physical
# count where kern.tcsm_available is set (CPUs that need the MDS workaround) and
# the logical count otherwise (RuntimeService::ClampedHardwareConcurrency), so
# either is real. Macs running WebGL on the Intel IGP have 2-8 physical cores,
# 4-16 logical.
INTEL_MAC_IGP_CORES = frozenset(LAUNCHER_CONSTANTS['intelMacIgpCores'])
# A discrete GPU adds the desktops, up to the 2019 Mac Pro's 28 cores (56
# threads). An eGPU puts one behind any Intel Mac, so the IGP counts stay in.
INTEL_MAC_DGPU_CORES = INTEL_MAC_IGP_CORES | frozenset(LAUNCHER_CONSTANTS['intelMacDgpuExtraCores'])

# The notched MacBook panels' scaled resolutions (Air 13.6"/15.3", Pro 14"/16")
# and the 24" iMac's default. Only Apple Silicon Macs have them.
APPLE_SILICON_PANELS = frozenset(
    (width, height)
    for panels in LAUNCHER_CONSTANTS['appleSiliconPanels'].values()
    for width, height in panels
)


class Violation(NamedTuple):
    rule: str
    detail: str
    #: The caller's own keys that the repair would have changed, and which were
    #: kept as passed instead. Empty when nothing of the caller's is involved.
    kept: Tuple[str, ...] = ()


class Rule(NamedTuple):
    name: str
    #: Returns a description of the breakage, or None when the identity holds.
    check: Callable[[Dict[str, Any], str], Optional[str]]
    #: Repairs the identity in place. None where no correct value is determined.
    repair: Optional[Callable[[Dict[str, Any], str], None]]
    #: Keys the repair only adjusts to stay consistent with what it repairs. A
    #: caller who set any of them keeps all of them as they were, the repair
    #: itself still runs, and they never block it.
    adjusts: Tuple[str, ...] = ()


def _renderer(config: Dict[str, Any]) -> str:
    return str(config.get('webGl:renderer') or '')


def _is_apple_silicon(config: Dict[str, Any]) -> bool:
    return 'Apple M' in _renderer(config)


def _check_apple_silicon_cores(config: Dict[str, Any], target_os: str) -> Optional[str]:
    if not _is_apple_silicon(config):
        return None
    cores = config.get('navigator.hardwareConcurrency')
    if isinstance(cores, int) and cores not in APPLE_SILICON_CORES:
        return f'{_renderer(config)!r} with hardwareConcurrency {cores}; Apple Silicon starts at 8'
    return None


def _repair_apple_silicon_cores(config: Dict[str, Any], target_os: str) -> None:
    cores = config.get('navigator.hardwareConcurrency')
    if not isinstance(cores, int):
        return
    # Snap UP to the nearest count Apple ships: a machine claiming an M-series
    # GPU has at least 8 cores, and a page timing workers can see how many.
    config['navigator.hardwareConcurrency'] = min(
        (c for c in sorted(APPLE_SILICON_CORES) if c >= cores), default=max(APPLE_SILICON_CORES)
    )


def gpu_fits_os(renderer: Optional[str], target_os: str) -> bool:
    """Whether this renderer string is one the OS can report.

    Used both to check a finished identity and to filter fpgen's GPUs before
    sampling, so the two can never disagree about what a Mac may claim.
    """
    renderer = str(renderer or '')
    if not renderer:
        return True
    if target_os == 'mac':
        return not any(bad in renderer for bad in _NOT_A_MAC_GPU)
    if target_os == 'win':
        return renderer.startswith('ANGLE')
    if target_os == 'lin':
        return 'ANGLE' not in renderer and 'Apple M' not in renderer
    return True


def _intel_mac_misfit(renderer: Optional[str], cores: Any, width: Any, height: Any) -> Optional[str]:
    """Why no Intel Mac reports this GPU beside these cores and this screen."""
    renderer = str(renderer or '')
    if not renderer or 'Apple M' in renderer:
        return None
    allowed = INTEL_MAC_IGP_CORES if 'Intel' in renderer else INTEL_MAC_DGPU_CORES
    if isinstance(cores, int) and cores not in allowed:
        return f'{renderer!r} with hardwareConcurrency {cores}; no Intel Mac with that GPU reports it'
    if (width, height) in APPLE_SILICON_PANELS:
        return f'{renderer!r} behind a {width}x{height} panel, which only Apple Silicon Macs have'
    return None


def gpu_fits_machine(
    renderer: Optional[str], target_os: str, cores: Any = None, width: Any = None, height: Any = None
) -> bool:
    """Whether a machine with this GPU has these cores and this screen.

    Only Intel Macs are modelled. Like gpu_fits_os, which it does not repeat,
    it serves both the WebGL draw and the finished-identity check.
    """
    return target_os != 'mac' or _intel_mac_misfit(renderer, cores, width, height) is None


def _check_intel_mac_hardware(config: Dict[str, Any], target_os: str) -> Optional[str]:
    if target_os != 'mac':
        return None
    return _intel_mac_misfit(
        _renderer(config),
        config.get('navigator.hardwareConcurrency'),
        config.get('screen.width'),
        config.get('screen.height'),
    )


def _check_gpu_matches_os(config: Dict[str, Any], target_os: str) -> Optional[str]:
    renderer = _renderer(config)
    if not renderer or gpu_fits_os(renderer, target_os):
        return None
    if target_os == 'mac':
        return f'macOS identity with {renderer!r}, which no Mac reports'
    if target_os == 'win':
        return f'Windows identity with {renderer!r}; Firefox on Windows renders through ANGLE'
    return f'Linux identity with {renderer!r}'


def _check_color_depth(config: Dict[str, Any], target_os: str) -> Optional[str]:
    depth = config.get('screen.colorDepth')
    if depth is None:
        return None
    if depth not in PLAUSIBLE_COLOR_DEPTH:
        return f'screen.colorDepth {depth}; Firefox reports 24 or 30'
    if target_os == 'mac' and depth != 30:
        return f'macOS identity with colorDepth {depth}; deep colour is the macOS default'
    return None


def _repair_color_depth(config: Dict[str, Any], target_os: str) -> None:
    if target_os == 'mac':
        config['screen.colorDepth'] = 30
    elif config.get('screen.colorDepth') not in PLAUSIBLE_COLOR_DEPTH:
        config['screen.colorDepth'] = 24
    config.setdefault('screen.pixelDepth', config['screen.colorDepth'])


def _check_pixel_depth(config: Dict[str, Any], target_os: str) -> Optional[str]:
    # pixelDepth is the same number in every browser that reports both.
    pixel = config.get('screen.pixelDepth')
    color = config.get('screen.colorDepth', 24)
    if pixel is not None and pixel != color:
        return f'screen.pixelDepth {pixel} differs from colorDepth {color}'
    return None


def _repair_pixel_depth(config: Dict[str, Any], target_os: str) -> None:
    config['screen.pixelDepth'] = config.get('screen.colorDepth', 24)


def _check_touch_points(config: Dict[str, Any], target_os: str) -> Optional[str]:
    touch = config.get('navigator.maxTouchPoints')
    if touch is None:
        return None
    if not isinstance(touch, int) or touch < 0 or touch > MAX_PLAUSIBLE_TOUCH_POINTS:
        return f'navigator.maxTouchPoints {touch}; a digitiser reports at most {MAX_PLAUSIBLE_TOUCH_POINTS}'
    if target_os == 'mac' and touch:
        return f'macOS identity with maxTouchPoints {touch}; no Mac has a touchscreen'
    return None


def _repair_touch_points(config: Dict[str, Any], target_os: str) -> None:
    touch = config.get('navigator.maxTouchPoints')
    too_many = isinstance(touch, int) and touch > MAX_PLAUSIBLE_TOUCH_POINTS
    if target_os == 'mac' or too_many or (touch is not None and not isinstance(touch, int)):
        # A machine claiming 256 contacts is not a machine with a better
        # touchscreen; the value is noise, so the identity has no digitiser.
        config['navigator.maxTouchPoints'] = 0


def _check_device_pixel_ratio(config: Dict[str, Any], target_os: str) -> Optional[str]:
    dpr = config.get('window.devicePixelRatio')
    if dpr is None:
        return None
    allowed = PLAUSIBLE_DPR.get(target_os)
    if allowed and float(dpr) not in {float(v) for v in allowed}:
        return f'window.devicePixelRatio {dpr} is not a display mode {target_os} offers'
    return None


# The CSS geometry a ratio scales: device pixels / devicePixelRatio.
CSS_GEOMETRY_KEYS = (
    'screen.width', 'screen.height', 'screen.availWidth', 'screen.availHeight',
    'screen.availLeft', 'screen.availTop',
    'window.outerWidth', 'window.outerHeight', 'window.innerWidth', 'window.innerHeight',
    'window.screenX', 'window.screenY',
)


def is_zoomed_ratio(dpr: Any, target_os: str) -> bool:
    """A devicePixelRatio no display mode of the OS offers: a browser zoom
    folded into the ratio, which scaled every CSS size with it."""
    allowed = PLAUSIBLE_DPR.get(target_os)
    if not allowed or isinstance(dpr, bool) or not isinstance(dpr, (int, float)) or dpr <= 0:
        return False
    return float(dpr) not in {float(v) for v in allowed}


def repair_device_pixel_ratio(config: Dict[str, Any], target_os: str,
                              target: Optional[float] = None) -> None:
    """Move the ratio to `target` (the scale a caller renders at) or else the
    nearest display mode, rescaling the CSS geometry so the screen stays the
    display behind it."""
    dpr = config.get('window.devicePixelRatio')
    allowed = PLAUSIBLE_DPR.get(target_os)
    if dpr is None or not allowed:
        return
    # Nearest real scaling step: 1.818 becomes 1.75 on Windows, 2 on macOS.
    step = target if target else min(allowed, key=lambda v: abs(float(v) - float(dpr)))
    config['window.devicePixelRatio'] = step
    # The scraped ratio has a browser zoom folded in, which shrank every CSS
    # size by it; the display behind it keeps its device pixels. Rescale to the
    # step so the screen is still that display: 1760x990 at 1.0909 is a
    # 1920x1080 monitor, so 1920x1080 at 1. Firefox rounds device / ratio.
    scale = float(dpr) / float(step)
    for key in CSS_GEOMETRY_KEYS:
        value = config.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            config[key] = int(round(value * scale))


def _check_window_chrome(config: Dict[str, Any], target_os: str) -> Optional[str]:
    inner = config.get('window.innerHeight')
    outer = config.get('window.outerHeight')
    if not inner or not outer:
        return None
    if outer - inner < BROWSER_CHROME_HEIGHT:
        return (f'window.outerHeight {outer} - innerHeight {inner} = {outer - inner}, less than the '
                f'{BROWSER_CHROME_HEIGHT}px of chrome the window actually has; the bottom '
                f'{BROWSER_CHROME_HEIGHT - (outer - inner)}px of the claimed viewport cannot receive input')
    return None


def _repair_window_chrome(config: Dict[str, Any], target_os: str) -> None:
    inner = config.get('window.innerHeight')
    outer = config.get('window.outerHeight')
    if not inner or not outer:
        return
    avail = config.get('screen.availHeight') or config.get('screen.height')
    # Prefer growing the window, which keeps the viewport the identity drew.
    if not avail or inner + BROWSER_CHROME_HEIGHT <= avail:
        config['window.outerHeight'] = inner + BROWSER_CHROME_HEIGHT
        return
    # No room on the claimed screen: shrink the viewport to what the window can
    # hold instead, so the claim matches the surface either way.
    config['window.innerHeight'] = max(outer - BROWSER_CHROME_HEIGHT, 1)


def _check_screen_shape(config: Dict[str, Any], target_os: str) -> Optional[str]:
    width, height = config.get('screen.width'), config.get('screen.height')
    if not width or not height:
        return None
    if height > width:
        return f'portrait screen {width}x{height}; desktop panels are landscape'
    if width < 1024:
        return f'screen {width}x{height} is smaller than any current desktop panel'
    return None


def _check_avail_bounds(config: Dict[str, Any], target_os: str) -> Optional[str]:
    width, height = config.get('screen.width'), config.get('screen.height')
    avail_w, avail_h = config.get('screen.availWidth'), config.get('screen.availHeight')
    if width and avail_w and avail_w > width:
        return f'screen.availWidth {avail_w} exceeds screen.width {width}'
    if height and avail_h and avail_h > height:
        return f'screen.availHeight {avail_h} exceeds screen.height {height}'
    return None


def _repair_avail_bounds(config: Dict[str, Any], target_os: str) -> None:
    width, height = config.get('screen.width'), config.get('screen.height')
    if width and config.get('screen.availWidth', 0) > width:
        config['screen.availWidth'] = width
    if height and config.get('screen.availHeight', 0) > height:
        config['screen.availHeight'] = height


# The CPU the identity claims: its architecture (cpu:arch) and manufacturer
# (cpu:manufacturer). Firefox's user agent and navigator never say (Firefox on
# ARM64 Linux reports "Linux x86_64", Windows on ARM an x86 platform, an Apple
# Silicon Mac "Intel Mac OS X"), but the values a page computes do: canvas
# pixels, Web Audio samples, encoded Opus, relaxed-SIMD wasm results and the
# sign of a NaN differ between x86-64 and ARM64, and within x86 the canvas and
# Opus differ between Intel and AMD (their RCPPS/RSQRTPS tables). Every ARM64
# chip computes as every other (an Apple M4 and a Cortex-A72 agree on all of
# them), so the manufacturer of an ARM CPU only has to agree with the GPU.
#
# Which manufacturers make each OS's machines:
#   mac      x86: Intel (every Intel Mac)    arm: Apple
#   windows  x86: Intel, AMD                 arm: Qualcomm (Snapdragon X; the
#            only Windows-on-ARM laptops on sale as of 2026-11)
#   linux    x86: Intel, AMD                 arm: Apple (Asahi), Qualcomm,
#            Broadcom (Raspberry Pi), NVIDIA, Ampere, Rockchip, MediaTek,
#            Amlogic, Allwinner
#
# The GPU decides where it can. Every Intel integrated GPU reads "Intel(R) HD
# Graphics" or "Intel(R) HD Graphics 400" (SanitizeRenderer.cpp), and only an
# Intel CPU carries one; Arc, the A750 bucket, is a discrete card too. "Radeon
# HD 3200 Graphics" is the bucket of AMD's integrated GPUs since Zen ("AMD
# Radeon(TM) Graphics") besides the Radeon HD 2000-4000 cards of 2007-2009, so
# on Windows and Linux it is taken as an AMD APU. Every x86 Mac has an Intel
# CPU, whatever GPU it reports, and an Apple GPU sits on an Apple CPU. An
# Adreno sits on a Qualcomm SoC, a VideoCore/V3D on a Broadcom one, a Mali on
# an ARM SoC of some other maker. Any other GPU is a discrete card or a bucket
# that leaves the CPU open.
#
# The core count can decide the x86 vendor too. Every AMD x86 CPU since 2015
# runs one or two threads per core, and its one-thread parts have 2 to 8
# cores, so it reports an even count with no 10, 14, 18, 22 or 28 (Wikipedia's
# lists of Ryzen and Athlon processors, Zen 5c hybrids included). Intel's
# hybrids reach those: the Core Ultra 5 225 reports 10, the 245K 14, the 125H
# 18, the 155H 22 and the i7-14700K 28. ARM chips reach them too (an M4 Pro
# has 14), so the rule is for x86 only.
CPU_ARCHES = ('x86', 'arm')
CPU_MANUFACTURERS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    os_: {arch: tuple(makers) for arch, makers in by_arch.items()}
    for os_, by_arch in LAUNCHER_CONSTANTS['cpuManufacturers'].items()
}
CPU_VENDORS = ('intel', 'amd')
INTEL_ONLY_CORE_COUNTS = frozenset(LAUNCHER_CONSTANTS['intelOnlyCoreCounts'])
_INTEL_IGPUS = ('Intel(R) HD Graphics, or similar', 'Intel(R) HD Graphics 400, or similar',
                'Intel(R) HD Graphics Direct3D11', 'Intel(R) HD Graphics 400 Direct3D11')
_AMD_IGPUS = ('Radeon HD 3200 Graphics',)
# ARM GPUs and the SoC makers that ship them.
_ARM_GPUS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ('Apple M', ('apple',)),
    ('Apple GPU', ('apple',)),
    ('Adreno', ('qualcomm',)),
    ('V3D', ('broadcom',)),
    ('VideoCore', ('broadcom',)),
    ('Mali', ('rockchip', 'mediatek', 'amlogic', 'allwinner')),
    ('Immortalis', ('mediatek',)),
    ('Tegra', ('nvidia',)),
)


def cpu_os(target_os: str) -> str:
    """The cpuManufacturers key for a launcher OS name (win, mac, lin, ...)."""
    return {'win': 'windows', 'windows': 'windows', 'mac': 'mac', 'macos': 'mac'}.get(target_os, 'linux')


def cpu_manufacturers(target_os: str, arch: str) -> Tuple[str, ...]:
    return CPU_MANUFACTURERS[cpu_os(target_os)].get(arch, ())


def resolve_cpu(cpu: Any, target_os: str) -> Dict[str, str]:
    """Check a caller's `cpu` option and fill in what it implies.

    Raises ValueError for anything no real machine running `target_os` is: an
    unknown key, architecture or manufacturer, or a pair such as an AMD Mac or
    an Apple x86 CPU. A manufacturer alone implies its architecture.
    """
    if not isinstance(cpu, dict):
        raise ValueError(f"cpu must be a dict such as {{'arch': 'x86', 'manufacturer': 'intel'}}, not {cpu!r}")
    unknown = sorted(set(cpu) - {'arch', 'manufacturer'})
    if unknown:
        raise ValueError(f"cpu takes 'arch' and 'manufacturer', not {', '.join(map(repr, unknown))}")
    arch, maker = cpu.get('arch'), cpu.get('manufacturer')
    if arch is not None and arch not in CPU_ARCHES:
        raise ValueError(f"cpu arch must be one of {CPU_ARCHES}, not {arch!r}")
    os_name = cpu_os(target_os)
    table = CPU_MANUFACTURERS[os_name]
    if maker is not None:
        arches = [a for a in CPU_ARCHES if maker in table.get(a, ())]
        if not arches:
            known = sorted({m for makers in table.values() for m in makers})
            raise ValueError(f"no {os_name} machine has a CPU made by {maker!r}; on {os_name} it is one of {', '.join(known)}")
        if arch is None:
            arch = arches[0]
        elif arch not in arches:
            raise ValueError(
                f"no {os_name} machine has an {arch} CPU made by {maker!r}; {os_name} {arch} CPUs are made by "
                f"{', '.join(table.get(arch, ())) or 'nobody'}"
            )
    elif arch is not None and not table.get(arch):
        raise ValueError(f"no {os_name} machine has an {arch} CPU")
    out = {}
    if arch is not None:
        out['cpu:arch'] = arch
    if maker is not None:
        out['cpu:manufacturer'] = maker
    return out


def gpu_cpu(renderer: Optional[str], target_os: str) -> Tuple[Optional[str], Tuple[str, ...]]:
    """The CPU architecture this GPU implies and the manufacturers it allows.

    (None, ()) when the GPU leaves both open. An empty tuple with an
    architecture means any maker of that architecture on `target_os`.
    """
    renderer = str(renderer or '')
    if not renderer:
        return None, ()
    for marker, makers in _ARM_GPUS:
        if marker in renderer:
            return 'arm', makers
    if cpu_os(target_os) == 'mac':
        return 'x86', ('intel',)
    if any(igpu in renderer for igpu in _INTEL_IGPUS):
        return 'x86', ('intel',)
    if any(igpu in renderer for igpu in _AMD_IGPUS):
        return 'x86', ('amd',)
    return None, ()


def gpu_fits_cpu(renderer: Optional[str], target_os: str, arch: Optional[str], maker: Optional[str]) -> bool:
    """Whether a machine with this GPU can have this CPU."""
    by_gpu, makers = gpu_cpu(renderer, target_os)
    if arch is None and maker is not None:
        arch = next((a for a in CPU_ARCHES if maker in cpu_manufacturers(target_os, a)), None)
    if arch is None or 'llvmpipe' in str(renderer or ''):
        # Mesa's software renderer draws on whatever CPU the machine has.
        return True
    if by_gpu is None:
        # A discrete card or an open bucket: an x86 machine. No ARM laptop or
        # board on sale carries a discrete GPU Firefox would name.
        return arch == 'x86' and cpu_os(target_os) != 'mac'
    if by_gpu != arch:
        return False
    return maker is None or not makers or maker in makers


def gpu_cpu_vendor(renderer: Optional[str], target_os: str) -> Optional[str]:
    """The x86 CPU vendor this GPU implies, or None when it leaves it open."""
    arch, makers = gpu_cpu(renderer, target_os)
    return makers[0] if arch == 'x86' and len(makers) == 1 else None


def cores_cpu_vendor(cores: Any) -> Optional[str]:
    """The x86 CPU vendor this navigator.hardwareConcurrency implies, or None."""
    return 'intel' if cores in INTEL_ONLY_CORE_COUNTS else None


def hardware_cpu(config: Dict[str, Any], target_os: str) -> Tuple[Optional[str], Optional[str]]:
    """The (arch, manufacturer) the identity's GPU or, failing that, its core count implies."""
    arch, makers = gpu_cpu(_renderer(config), target_os)
    if arch == 'arm':
        return arch, makers[0] if len(makers) == 1 else None
    vendor = (makers[0] if makers else None) or cores_cpu_vendor(config.get('navigator.hardwareConcurrency'))
    return ('x86' if vendor or arch else None), vendor


def hardware_cpu_vendor(config: Dict[str, Any], target_os: str) -> Optional[str]:
    """The x86 CPU vendor the identity's GPU or, failing that, its core count implies."""
    arch, maker = hardware_cpu(config, target_os)
    return maker if arch == 'x86' else None


def cpu_conflict(config: Dict[str, Any], target_os: str) -> Optional[str]:
    """Why the claimed CPU cannot sit in this machine, or None."""
    arch, maker = config.get('cpu:arch'), config.get('cpu:manufacturer')
    if arch is None and maker is None:
        return None
    try:
        resolve_cpu({k: v for k, v in (('arch', arch), ('manufacturer', maker)) if v is not None}, target_os)
    except ValueError as exc:
        return str(exc)
    renderer = _renderer(config)
    claimed = ' '.join(str(v) for v in (maker, arch) if v)
    if renderer and not gpu_fits_cpu(renderer, target_os, arch, maker):
        return f'CPU {claimed} beside {renderer!r}'
    cores = config.get('navigator.hardwareConcurrency')
    if (arch or 'x86') == 'x86' and maker and maker != cores_cpu_vendor(cores) and cores_cpu_vendor(cores):
        return f'CPU {claimed} with hardwareConcurrency {cores}, which only an Intel CPU reports'
    return None


def _check_cpu(config: Dict[str, Any], target_os: str) -> Optional[str]:
    return cpu_conflict(config, target_os)


def _repair_cpu(config: Dict[str, Any], target_os: str) -> None:
    # The GPU decides. An AMD APU's GPU beside an Intel-only core count stays
    # reported: no vendor matches both.
    arch, maker = hardware_cpu(config, target_os)
    if arch is None:
        arch = 'x86'
    config['cpu:arch'] = arch
    if maker:
        config['cpu:manufacturer'] = maker
    elif config.get('cpu:manufacturer') not in cpu_manufacturers(target_os, arch) or cpu_conflict(config, target_os):
        config.pop('cpu:manufacturer', None)


def _check_arch_agreement(config: Dict[str, Any], target_os: str) -> Optional[str]:
    ua = str(config.get('navigator.userAgent') or '')
    platform = str(config.get('navigator.platform') or '')
    oscpu = str(config.get('navigator.oscpu') or '')
    if not ua:
        return None
    if 'x86_64' in ua and ('armv' in platform or 'armv' in oscpu):
        return f'user agent claims x86_64 while platform/oscpu say {platform!r}/{oscpu!r}'
    return None


RULES: List[Rule] = [
    Rule('apple-silicon-cores', _check_apple_silicon_cores, _repair_apple_silicon_cores),
    Rule('gpu-matches-os', _check_gpu_matches_os, None),
    Rule('intel-mac-hardware', _check_intel_mac_hardware, None),
    Rule('color-depth', _check_color_depth, _repair_color_depth),
    Rule('pixel-depth', _check_pixel_depth, _repair_pixel_depth),
    Rule('touch-points', _check_touch_points, _repair_touch_points),
    Rule('device-pixel-ratio', _check_device_pixel_ratio, repair_device_pixel_ratio, CSS_GEOMETRY_KEYS),
    Rule('window-chrome', _check_window_chrome, _repair_window_chrome),
    Rule('screen-shape', _check_screen_shape, None),
    Rule('avail-bounds', _check_avail_bounds, _repair_avail_bounds),
    Rule('arch-agreement', _check_arch_agreement, None),
    Rule('cpu-matches-hardware', _check_cpu, _repair_cpu),
]


def screen_is_implausible(config: Dict[str, Any]) -> bool:
    """Whether the screen is one no desktop reports (portrait, or tiny)."""
    return _check_screen_shape(config, '') is not None


def repair_screen_orientation(config: Dict[str, Any]) -> bool:
    """Turn a portrait screen landscape, keeping the panel's own dimensions.

    One bundled preset reports 1440x2560: a phone panel, or a desktop one
    captured while rotated. Either way a desktop identity that claims it is
    answering a `matchMedia('(orientation: portrait)')` the way no desktop
    does, so the axes are swapped rather than the numbers invented. Run before
    the window clamps, which then bound the window to the new screen.
    """
    width, height = config.get('screen.width'), config.get('screen.height')
    if not width or not height or height <= width:
        return False
    config['screen.width'], config['screen.height'] = height, width
    avail_w, avail_h = config.get('screen.availWidth'), config.get('screen.availHeight')
    if avail_w and avail_h:
        config['screen.availWidth'], config['screen.availHeight'] = avail_h, avail_w
    return True


def _changed(before: Dict[str, Any], after: Dict[str, Any], keys: AbstractSet[str]) -> Tuple[str, ...]:
    return tuple(sorted(k for k in keys if (k in before) != (k in after) or before.get(k) != after.get(k)))


def drop_incoherent_source_values(
    config: Dict[str, Any], target_os: str, keep: AbstractSet[str] = frozenset()
) -> List[Violation]:
    """Discard values a source supplied that this identity cannot keep.

    Run after the core count and the screen are final, and before the pools
    that would otherwise defer to them. A preset carries its own GPU pair, so a
    macOS preset naming an Intel IGP keeps it all the way to the page unless
    the pair is dropped here -- including when the launch has replaced the
    preset's core count with a 20-core host's -- at which point the normal
    WebGL sampling draws a coherent one instead.

    Only values that another pool can replace are dropped. Everything else is
    left for `apply()` to repair or report. A GPU the caller passed (a key in
    `keep`) is never dropped: it is reported, with the keys it kept, instead.
    """
    renderer = _renderer(config)
    if not renderer:
        return []
    if not gpu_fits_os(renderer, target_os):
        rule = 'gpu-matches-os'
    elif _check_intel_mac_hardware(config, target_os):
        rule = 'intel-mac-hardware'
    else:
        return []
    kept = _changed(config, {}, keep & {'webGl:renderer', 'webGl:vendor'})
    if kept:
        return [Violation(rule, f'{renderer!r} does not fit this {target_os} identity', kept)]
    config.pop('webGl:renderer', None)
    config.pop('webGl:vendor', None)
    return [Violation(rule, f'dropped {renderer!r} for a {target_os} identity')]


def validate(config: Dict[str, Any], target_os: str) -> List[Violation]:
    """Every invariant this identity breaks. Empty means coherent."""
    violations = []
    for rule in RULES:
        detail = rule.check(config, target_os)
        if detail:
            violations.append(Violation(rule.name, detail))
    return violations


def apply(config: Dict[str, Any], target_os: str, keep: AbstractSet[str] = frozenset()) -> List[Violation]:
    """Repair what is determined, and report what is left.

    A rule with no repair -- a Windows GPU on a macOS identity, a portrait
    screen -- cannot be corrected without inventing a machine, so it is
    returned for the caller to decide about. The caller that draws the identity
    can simply draw again.

    `keep` names the keys the caller set. A repair that would change one of
    them is not made: the caller's value stands, and the violation comes back
    with those keys in `kept` so the launcher can warn about it (#956). A
    repair that only touches other keys (growing outerHeight to fit a caller's
    innerHeight) still runs.
    """
    kept: Dict[str, Tuple[str, ...]] = {}
    for rule in RULES:
        if not rule.repair or not rule.check(config, target_os):
            continue
        repaired = dict(config)
        rule.repair(repaired, target_os)
        if rule.adjusts and keep.intersection(rule.adjusts):
            for key in rule.adjusts:
                if key in config:
                    repaired[key] = config[key]
                else:
                    repaired.pop(key, None)
        blocked = _changed(config, repaired, keep)
        if blocked:
            kept[rule.name] = blocked
        else:
            config.clear()
            config.update(repaired)
    return [v._replace(kept=kept.get(v.rule, ())) for v in validate(config, target_os)]
