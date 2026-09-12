"""Fixtures for Camoufox's own suite.

Separate from `tests/` (upstream Playwright's suite, forked) and
`tests/patches/` (one standalone guard per spoofing behaviour). This suite is
for the things only Camoufox can be asked about: that it cleans up after itself,
that a context and a browser mean what we say they mean, and that decisions the
project has already made are still in force.

Run:
    python3 -m ci.run_native --binary path/to/camoufox-bin
    CAMOUFOX_EXECUTABLE_PATH=... python3 -m pytest native-tests -q
"""

from __future__ import annotations

import gc
import os
import resource
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pythonlib"))

# Names a leaked browser or display process could be running under.
BROWSER_NAMES = ("camoufox", "camoufox-bin", "firefox", "firefox-bin")
DISPLAY_NAMES = ("Xvfb",)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--browsers", type=int, default=3,
                     help="how many browsers the leak tests launch per round")
    parser.addoption("--rounds", type=int, default=3,
                     help="how many launch/close rounds the leak tests run")


@pytest.fixture(scope="session")
def binary() -> Path:
    path = os.environ.get("CAMOUFOX_EXECUTABLE_PATH") or os.environ.get("CAMOUFOX_BINARY")
    if not path:
        pytest.skip("no CAMOUFOX_EXECUTABLE_PATH; these tests need a built browser")
    resolved = Path(path).resolve()
    if not resolved.is_file():
        pytest.skip(f"CAMOUFOX_EXECUTABLE_PATH points at nothing: {resolved}")
    return resolved


@pytest.fixture(scope="session")
def psutil_mod():
    return pytest.importorskip("psutil", reason="the leak tests need psutil")


# ---------------------------------------------------------------------------
# leak accounting
# ---------------------------------------------------------------------------


@dataclass
class Snapshot:
    """What this process is holding at one moment.

    Deliberately measured from *our* side of the fence. We can see our own file
    descriptors, our own sockets, and which children are still alive; we cannot
    see inside a browser process's heap, and this suite does not pretend to.
    What it does prove is the failure that actually bites in production: a long
    -running script that launches browsers in a loop and slowly runs out of file
    descriptors, ports, or child slots.
    """

    fds: Set[int] = field(default_factory=set)
    sockets: int = 0
    children: Dict[int, str] = field(default_factory=dict)
    rss_kb: int = 0
    x11_sockets: Set[str] = field(default_factory=set)

    @property
    def fd_count(self) -> int:
        return len(self.fds)


def _x11_artifacts() -> Set[str]:
    """Stale X11 lock and socket files, which block later display allocation."""
    out: Set[str] = set()
    for pattern, directory in ((".X*-lock", Path("/tmp")), ("X*", Path("/tmp/.X11-unix"))):
        try:
            out.update(str(p) for p in directory.glob(pattern))
        except OSError:
            continue
    return out


def take_snapshot(psutil_mod) -> Snapshot:
    proc = psutil_mod.Process()
    try:
        fds = {int(p.name) for p in Path("/proc/self/fd").iterdir() if p.name.isdigit()}
    except OSError:
        fds = set(range(proc.num_fds()))

    try:
        sockets = len(proc.net_connections(kind="all"))
    except (psutil_mod.AccessDenied, AttributeError):
        sockets = 0

    children: Dict[int, str] = {}
    for child in proc.children(recursive=True):
        try:
            children[child.pid] = child.name()
        except psutil_mod.NoSuchProcess:
            continue

    return Snapshot(
        fds=fds,
        sockets=sockets,
        children=children,
        rss_kb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        x11_sockets=_x11_artifacts(),
    )


def settle(psutil_mod, timeout: float = 20.0) -> None:
    """Wait for children to exit and descriptors to close.

    Teardown is not instantaneous: the driver has to notice the browser is gone,
    the OS has to reap it, and sockets sit in TIME_WAIT. Polling for quiescence
    rather than sleeping a fixed amount keeps the tests fast when things work
    and honest when they do not.
    """
    gc.collect()
    proc = psutil_mod.Process()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [c for c in proc.children(recursive=True)]
        if not alive:
            break
        gone, _ = psutil_mod.wait_procs(alive, timeout=0.5)
        if not gone:
            time.sleep(0.25)
    gc.collect()
    time.sleep(0.5)


class DescendantSampler:
    """Record every process this test starts, so orphans can be named later.

    An earlier version of this scanned the whole process table for anything
    called camoufox or Xvfb. That is wrong on any machine that is also being
    used for something else -- it flagged the developer's own browsers -- and it
    is the kind of false positive that gets a suite switched off. Sampling our
    own descendants while the test runs is precise: a PID recorded here and
    still alive after teardown is unambiguously ours and unambiguously leaked,
    even if it has been reparented to init in the meantime.
    """

    def __init__(self, psutil_mod, interval: float = 0.25) -> None:
        self._psutil = psutil_mod
        self._interval = interval
        self._seen: Dict[int, str] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # Python starts these itself and keeps them for the life of the interpreter.
    # They are not ours to clean up, and flagging them made every leak test fail
    # with a survivor that was never a browser.
    _STDLIB_HELPERS = ("resource_tracker", "semaphore_tracker", "forkserver")

    def _is_stdlib_helper(self, proc) -> bool:
        try:
            return any(h in " ".join(proc.cmdline()) for h in self._STDLIB_HELPERS)
        except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
            return False

    def _poll(self) -> None:
        proc = self._psutil.Process()
        while not self._stop.is_set():
            try:
                for child in proc.children(recursive=True):
                    try:
                        if self._is_stdlib_helper(child):
                            continue
                        self._seen.setdefault(child.pid, child.name())
                    except self._psutil.NoSuchProcess:
                        continue
            except self._psutil.Error:
                pass
            self._stop.wait(self._interval)

    def start(self) -> "DescendantSampler":
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def survivors(self) -> List[str]:
        """PIDs we started that are still alive, reparenting included."""
        out = []
        for pid, name in self._seen.items():
            try:
                proc = self._psutil.Process(pid)
                if proc.is_running() and proc.status() != self._psutil.STATUS_ZOMBIE:
                    out.append(f"{name}({pid}, now ppid={proc.ppid()})")
            except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                continue
        return out


@pytest.fixture
def leak_check(psutil_mod):
    """Snapshot before, snapshot after, and fail on the difference.

    File descriptors get a tolerance and processes do not, deliberately. A
    couple of sockets sitting in TIME_WAIT after a launch is the kernel doing
    its job, not a leak; a browser process still running after close() returned
    is never anything but a leak. The per-round scaling tests are where a real
    descriptor leak shows up, because that is the shape it actually has.
    """

    @dataclass
    class Checker:
        before: Snapshot
        sampler: "DescendantSampler"

        def assert_clean(self, *, allow_fds: int = 8) -> None:
            settle(psutil_mod)
            self.sampler.stop()
            after = take_snapshot(psutil_mod)

            problems: List[str] = []

            survivors = self.sampler.survivors()
            if survivors:
                problems.append(
                    f"{len(survivors)} process(es) this test started are still alive: "
                    + ", ".join(survivors[:10])
                )

            new_x11 = after.x11_sockets - self.before.x11_sockets
            if new_x11:
                problems.append(
                    f"stale X11 artefacts left behind: {sorted(new_x11)[:10]}. These block "
                    "that display number for every later process on the machine."
                )

            new_fds = after.fds - self.before.fds
            if len(new_fds) > allow_fds:
                detail = []
                for fd in sorted(new_fds)[:12]:
                    try:
                        detail.append(f"{fd} -> {os.readlink(f'/proc/self/fd/{fd}')}")
                    except OSError:
                        detail.append(str(fd))
                problems.append(
                    f"{len(new_fds)} file descriptor(s) still open (tolerance {allow_fds}): "
                    + ", ".join(detail)
                )

            assert not problems, "resources leaked:\n  - " + "\n  - ".join(problems)

    settle(psutil_mod)
    checker = Checker(before=take_snapshot(psutil_mod), sampler=DescendantSampler(psutil_mod).start())
    yield checker
    checker.sampler.stop()


def fd_count() -> int:
    """This process's open descriptors, for the scaling tests."""
    try:
        return len([p for p in Path("/proc/self/fd").iterdir() if p.name.isdigit()])
    except OSError:
        import resource as _resource

        return _resource.getrlimit(_resource.RLIMIT_NOFILE)[0]
