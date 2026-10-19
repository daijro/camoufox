"""
Host display geometry, in the units Firefox lays its windows out in.

Firefox sizes windows in **CSS pixels**, but `screeninfo` marks the process
per-monitor DPI aware and therefore reports **physical** pixels. Where Windows
display scaling is enabled the two differ by the scale factor: a 1920x1080 panel
at 150% is only 1280x720 CSS px. Deriving a window size from the physical
numbers overshoots the screen by that factor, so the window opens partly
off-screen (daijro/camoufox#425).

macOS (`NSScreen.frame`) and X11 (xrandr) already report CSS pixels, so scaling
only ever applies on Windows.
"""

from typing import Any, Mapping, NamedTuple, Optional

from screeninfo import get_monitors

from .pkgman import OS_NAME

# Windows expresses DPI relative to this baseline: 144 DPI == 150% scaling.
_WINDOWS_BASE_DPI = 96

# shcore.h / winuser.h constants
_MDT_EFFECTIVE_DPI = 0
_MONITOR_DEFAULTTONEAREST = 2


class DisplaySize(NamedTuple):
    """Size of a monitor in CSS pixels."""

    width: int
    height: int


def has_display(env: Mapping[str, Any]) -> bool:
    """
    Whether the host has a desktop session for Camoufox's window to open on.

    DISPLAY / WAYLAND_DISPLAY only ever exist on Linux, so they cannot be the
    sole probe: keying off DISPLAY alone skipped the screen constraints entirely
    on Windows and macOS, where a session is always present.
    """
    if OS_NAME != 'lin':
        return True
    return bool(env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'))


def largest_display() -> Optional[DisplaySize]:
    """
    Size of the roomiest attached monitor in CSS pixels, or None when the
    display cannot be probed (no monitors, or enumeration failed).
    """
    try:
        monitors = get_monitors()
    except Exception:
        return None
    if not monitors:
        return None

    monitor = max(monitors, key=lambda m: m.width * m.height)
    scale = _scale_factor(monitor)
    return DisplaySize(
        width=max(1, int(monitor.width / scale)),
        height=max(1, int(monitor.height / scale)),
    )


def _scale_factor(monitor: Any) -> float:
    """
    Physical pixels per CSS pixel on `monitor`. Always 1.0 outside Windows.
    """
    if OS_NAME != 'win':
        return 1.0
    try:
        dpi = _windows_monitor_dpi(monitor)
    except Exception:
        return 1.0  # Pre-Windows 8.1, or the shcore call is unavailable
    return dpi / _WINDOWS_BASE_DPI if dpi > 0 else 1.0


def _windows_monitor_dpi(monitor: Any) -> int:
    """
    Effective DPI of `monitor`, via shcore!GetDpiForMonitor (Windows 8.1+).

    Private WinDLL handles are used rather than the process-wide `ctypes.windll`
    cache so that annotating the prototypes cannot affect other libraries.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32')  # type: ignore[attr-defined]
    user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    handle = user32.MonitorFromPoint(
        wintypes.POINT(int(monitor.x), int(monitor.y)), _MONITOR_DEFAULTTONEAREST
    )

    shcore = ctypes.WinDLL('shcore')  # type: ignore[attr-defined]
    shcore.GetDpiForMonitor.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
    )
    shcore.GetDpiForMonitor.restype = ctypes.c_long  # HRESULT
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()

    hresult = shcore.GetDpiForMonitor(
        handle, _MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
    )
    if hresult != 0:
        raise OSError(f'GetDpiForMonitor failed (0x{hresult & 0xFFFFFFFF:08X})')
    return dpi_x.value
