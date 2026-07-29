"""Profile disk / window operations for console."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any, Optional

# Directories/files safe to wipe when clearing cache (keep cookies, places, prefs, extensions)
CACHE_NAMES = (
    "cache2",
    "startupCache",
    "thumbnails",
    "shader-cache",
    "OfflineCache",
    "jumpListCache",
    "safebrowsing",
    "activity-stream.weather_feed.json",
)


def du_mb(path: str | Path) -> float:
    root = Path(path)
    if not root.is_dir():
        return 0.0
    total = 0
    try:
        for p in root.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0.0
    return round(total / (1024 * 1024), 1)


def clear_profile_cache(profile_path: str | Path) -> list[str]:
    """Remove cache dirs; return list of removed names."""
    root = Path(profile_path)
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for name in CACHE_NAMES:
        target = root / name
        if not target.exists():
            continue
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            removed.append(name)
        except OSError:
            continue
    return removed


def reset_profile_dir(profile_path: str | Path) -> None:
    """Wipe profile directory contents and recreate empty dir."""
    root = Path(profile_path)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)


def focus_window_by_pid(pid: int) -> bool:
    """Bring a top-level window owned by pid to the foreground. Windows-first."""
    if sys.platform != "win32":
        # Best-effort: no-op on non-Windows for MVP
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):  # type: ignore[no-untyped-def]
        if not user32.IsWindowVisible(hwnd):
            return True
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if int(proc_id.value) == int(pid):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not found:
        # Also try child processes: scan all windows for any camoufox under same tree — skip for MVP
        return False

    hwnd = found[0]
    # Allow SetForegroundWindow
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


def process_stats(pid: Optional[int]) -> dict[str, Any]:
    """Return cpuPercent / memoryMb for a PID via psutil if available."""
    if not pid:
        return {"cpuPercent": None, "memoryMb": None}
    try:
        import psutil

        p = psutil.Process(int(pid))
        # first call often returns 0; small interval
        cpu = p.cpu_percent(interval=0.05)
        mem = p.memory_info().rss / (1024 * 1024)
        # include children (Firefox content processes)
        for c in p.children(recursive=True):
            try:
                cpu += c.cpu_percent(interval=0.0)
                mem += c.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"cpuPercent": round(cpu, 1), "memoryMb": round(mem, 1)}
    except Exception:
        return {"cpuPercent": None, "memoryMb": None}


def system_stats() -> dict[str, Any]:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return {
            "cpuPercent": round(psutil.cpu_percent(interval=0.1), 1),
            "memoryUsedMb": round(vm.used / (1024 * 1024), 1),
            "memoryTotalMb": round(vm.total / (1024 * 1024), 1),
        }
    except Exception:
        return {
            "cpuPercent": None,
            "memoryUsedMb": None,
            "memoryTotalMb": None,
        }
