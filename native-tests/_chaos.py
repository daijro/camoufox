"""Helpers for killing things and watching what survives.

Camoufox's real process tree, as observed rather than assumed:

    python (the test)
    ├── node                  Playwright's driver
    │   └── camoufox-bin      the browser parent
    │       ├── Socket Process
    │       └── forkserver
    │           ├── Web Content     one per content process
    │           ├── RDD Process     media decoder
    │           └── WebExtensions
    ├── Xvfb                  only under headless="virtual"
    └── python3               stdlib multiprocessing.resource_tracker

Every one of those can die badly in production -- OOM killer, a segfault, a
container reaping a process group, an X server going away. What matters is not
that the browser survives (often it cannot) but that the failure is *bounded and
clean*: the call returns instead of hanging forever, and nothing is left behind
to accumulate.

Targeting is always restricted to this process's own descendants. A test that
went looking for "anything called camoufox" would kill the developer's browser.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import pytest

# Names as the kernel reports them, from an observed tree.
DRIVER = "node"
BROWSER = "camoufox-bin"
SOCKET_PROCESS = "Socket Process"
FORKSERVER = "forkserver"
WEB_CONTENT = "Web Content"
RDD = "RDD Process"
WEB_EXTENSIONS = "WebExtensions"
XVFB = "Xvfb"

_STDLIB_HELPERS = ("resource_tracker", "semaphore_tracker")

# Short-lived probes Gecko spawns at startup and deliberately does not wait for.
# glxtest asks the GL stack what it supports; vaapitest does the same for video
# decode. Both detach, answer, and exit on their own, and on a runner with no GPU
# glxtest can outlive a browser that has already gone. Counting one as a leaked
# process is wrong twice over: it is not ours to reap, and it does not stay.
_GECKO_PROBES = ("glxtest", "vaapitest")


@dataclass
class Victim:
    pid: int
    name: str

    def __str__(self) -> str:
        return f"{self.name}({self.pid})"


def descendants(psutil_mod, *, name: Optional[str] = None) -> List:
    """Our own descendants, optionally filtered by process name."""
    out = []
    for proc in psutil_mod.Process().children(recursive=True):
        try:
            if any(h in " ".join(proc.cmdline()) for h in _STDLIB_HELPERS):
                continue
            if proc.name() in _GECKO_PROBES:
                continue
            if name is None or proc.name() == name:
                out.append(proc)
        except (psutil_mod.NoSuchProcess, psutil_mod.AccessDenied):
            continue
    return out


def driver_process(psutil_mod, *, timeout: float = 30.0):
    """Playwright's driver, found by position rather than by name.

    It is `node` on a developer machine and something else on a CI runner --
    an observed tree there had MainThread, camoufox-bin, forkserver and no node
    at all, so a test keyed on the name failed for a reason that had nothing to
    do with what it was checking.

    Position is stable where the name is not: the driver is whatever launched
    the browser, so look for the browser and walk up one.
    """
    browser = wait_for_process(psutil_mod, BROWSER, timeout=timeout)[0]
    me = psutil_mod.Process().pid
    try:
        parent = browser.parent()
    except psutil_mod.Error:
        parent = None
    if parent is None or parent.pid == me:
        return None  # launched directly by us; there is no separate driver
    return parent


def wait_for_process(psutil_mod, name: str, *, timeout: float = 30.0) -> List:
    """Block until at least one process of this name is a descendant."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = descendants(psutil_mod, name=name)
        if found:
            return found
        time.sleep(0.2)
    have = sorted({p.name() for p in descendants(psutil_mod)})
    raise AssertionError(f"no {name!r} process appeared within {timeout}s; saw {have}")


def sigkill(psutil_mod, name: str, *, count: int = 1, timeout: float = 30.0) -> List[Victim]:
    """SIGKILL up to `count` descendants named `name`. Returns what was killed.

    SIGKILL rather than SIGTERM on purpose: this is simulating a crash or an
    OOM kill, not a polite shutdown. A process given the chance to clean up
    after itself is not the case that leaks.
    """
    targets = wait_for_process(psutil_mod, name, timeout=timeout)[:count]
    killed = []
    for proc in targets:
        try:
            victim = Victim(proc.pid, proc.name())
            proc.kill()
            killed.append(victim)
        except (psutil_mod.NoSuchProcess, psutil_mod.AccessDenied):
            continue
    psutil_mod.wait_procs([p for p in targets], timeout=10)
    return killed


async def bounded(awaitable, seconds: float, what: str):
    """Run something with a deadline, and fail loudly rather than hang.

    "Does the browser hang?" is the question half this suite exists to answer,
    so a hang has to be an assertion failure with a name attached -- not a job
    that sits at 0% CPU until the runner's timeout kills it an hour later and
    tells you nothing.
    """
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError:
        raise AssertionError(
            f"{what} did not return within {seconds}s -- it hung. This is the failure "
            "mode that wedges a long-running scraper: no error, no CPU, no diagnostic."
        ) from None
    except Exception:
        # Raising is fine and often correct after a crash; hanging is not.
        return None


async def close_bounded(target, seconds: float = 60.0, what: str = "close()"):
    """close() something that may already be dead, within a deadline."""
    return await bounded(target.close(), seconds, what)


def x11_artifacts_for(display: str) -> List[str]:
    """The lock and socket a given ':N' display owns."""
    index = display.lstrip(":")
    return [f"/tmp/.X{index}-lock", f"/tmp/.X11-unix/X{index}"]
