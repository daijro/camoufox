"""Pin the browser to as many CPU cores as the identity reports.

navigator.hardwareConcurrency is spoofed by the browser, but the number of
cores a page can *measure* (timing N parallel workers) is the number the OS
lets the browser run on. Reporting the fingerprint's value and pinning the
browser's CPU affinity to that many cores makes the two agree, so the drawn
value survives instead of being replaced by the host count.

The pin is applied to the Playwright driver process right before the browser
is launched -- child processes inherit the affinity mask on Linux and Windows,
so the browser and every content/GPU process it spawns run on the pinned set
-- and lifted from the driver again afterwards. macOS has no process affinity
API, so nothing can be pinned there and the launcher falls back to reporting
the host's (snapped) count.
"""

import os
import platform
import random
from typing import Iterable, List, Optional, Sequence


def supported() -> bool:
    """Whether this host can constrain a process to a subset of its cores."""
    system = platform.system()
    if system == 'Linux':
        return hasattr(os, 'sched_setaffinity')
    return system == 'Windows'


def host_cores() -> Optional[List[int]]:
    """The cores this process may run on, in order."""
    try:
        if hasattr(os, 'sched_getaffinity'):
            return sorted(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except OSError:
        pass
    if platform.system() == 'Windows':
        mask = _win_get_mask(os.getpid())
        if mask:
            return _mask_to_cores(mask)
    n = os.cpu_count()
    return list(range(n)) if n else None


def _pick(cores: Sequence[int], count: int) -> List[int]:
    """`count` adjacent cores from a random starting point (wrapping). Always
    taking the first `count` stacked every browser on one host onto cores
    0..count-1, so concurrent browsers measured far less parallelism than they
    report; adjacent cores keep the SMT topology a real machine of that size
    would have."""
    start = random.randrange(len(cores))
    return sorted((list(cores[start:]) + list(cores[:start]))[:count])


def pin(pid: int, count: int) -> Optional[Sequence[int]]:
    """Restrict `pid` to `count` of its cores. Returns the previous set so it
    can be handed back to `restore()`, or None if nothing was changed.

    The caller must not pin the same process for two launches at once: the
    browser inherits whatever mask the driver has when it is spawned."""
    if count < 1 or not supported():
        return None
    system = platform.system()
    if system == 'Linux':
        try:
            before = sorted(os.sched_getaffinity(pid))  # type: ignore[attr-defined]
            if count >= len(before):
                return None
            os.sched_setaffinity(pid, set(_pick(before, count)))  # type: ignore[attr-defined]
            return before
        except OSError:
            return None
    if system == 'Windows':
        before_mask = _win_get_mask(pid)
        if not before_mask:
            return None
        before = _mask_to_cores(before_mask)
        if count >= len(before):
            return None
        return before if _win_set_mask(pid, _cores_to_mask(_pick(before, count))) else None
    return None


def restore(pid: int, previous: Optional[Sequence[int]]) -> None:
    """Give `pid` back the cores it had before `pin()`."""
    if not previous:
        return
    system = platform.system()
    try:
        if system == 'Linux':
            os.sched_setaffinity(pid, set(previous))  # type: ignore[attr-defined]
        elif system == 'Windows':
            _win_set_mask(pid, _cores_to_mask(previous))
    except OSError:
        pass


# -- Windows ---------------------------------------------------------------

_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_SET_INFORMATION = 0x0200


def _mask_to_cores(mask: int) -> List[int]:
    return [i for i in range(mask.bit_length()) if mask >> i & 1]


def _cores_to_mask(cores: Iterable[int]) -> int:
    mask = 0
    for c in cores:
        mask |= 1 << c
    return mask


def _win_handle(pid: int):
    import ctypes

    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    return k32, k32.OpenProcess(_PROCESS_QUERY_INFORMATION | _PROCESS_SET_INFORMATION, False, pid)


def _win_get_mask(pid: int) -> int:
    try:
        import ctypes

        k32, h = _win_handle(pid)
        if not h:
            return 0
        try:
            proc_mask = ctypes.c_size_t()
            sys_mask = ctypes.c_size_t()
            if not k32.GetProcessAffinityMask(h, ctypes.byref(proc_mask), ctypes.byref(sys_mask)):
                return 0
            return int(proc_mask.value)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return 0


def _win_set_mask(pid: int, mask: int) -> bool:
    try:
        import ctypes

        k32, h = _win_handle(pid)
        if not h:
            return False
        try:
            return bool(k32.SetProcessAffinityMask(h, ctypes.c_size_t(mask)))
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False
