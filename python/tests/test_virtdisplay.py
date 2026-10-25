"""
Tests for camoufox.virtdisplay.

Mirrors typescript/tests/virtdisplay.test.ts.

Run with:
    cd python && python -m pytest tests/test_virtdisplay.py -v

VIRTDISPLAY_TEST_N controls the concurrent-launch count. Default is kept
low so the test passes on any developer box; set to e.g. 1000 to exercise
real scaling. At high N you will need `ulimit -n` headroom -- each Xvfb
takes one X11 socket plus our -displayfd pipe.
"""

import os
import re
import signal
import subprocess  # nosec
import sys
import time
from typing import List, Set

import pytest

from camoufox.virtdisplay import VirtualDisplay

DISPLAY_RE = re.compile(r"^:\d+$")
N = int(os.environ.get("VIRTDISPLAY_TEST_N", "50"))

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="VirtualDisplay is Linux-only"
)


# Track every VirtualDisplay we spawn so the fixture can guarantee
# cleanup even if an assertion fails mid-test.
@pytest.fixture
def tracked() -> List[VirtualDisplay]:
    items: List[VirtualDisplay] = []
    yield items
    for vd in items:
        try:
            vd.kill()
        except Exception:
            pass


def _track(items: List[VirtualDisplay], vd: VirtualDisplay) -> VirtualDisplay:
    items.append(vd)
    return vd


def _wait_for_exit(vd: VirtualDisplay, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if vd.proc is None or vd.proc.poll() is not None:
            return
        time.sleep(0.025)


def test_single_launch_returns_valid_display_and_kill_terminates_xvfb(tracked):
    vd = _track(tracked, VirtualDisplay())
    display = vd.get()
    assert DISPLAY_RE.match(display), display
    assert vd.proc is not None
    assert vd.proc.poll() is None  # alive

    vd.kill()
    _wait_for_exit(vd)
    # kill() reaps the child and clears the handle, so `proc is None` is the
    # post-condition; a surviving handle must at least report an exit code.
    assert vd.proc is None or vd.proc.poll() is not None  # exited


def test_get_is_idempotent_within_one_virtual_display(tracked):
    vd = _track(tracked, VirtualDisplay())
    a = vd.get()
    b = vd.get()
    assert a == b


def test_concurrent_reservations_all_get_unique_displays(tracked):
    # Every VirtualDisplay spawns its own Xvfb. Each Xvfb scans up from :0
    # and atomically claims the first free X11 socket (kernel-mediated
    # bind, no userspace race). -displayfd reports the chosen number back
    # to us. A duplicate here would mean we mis-parsed or mis-routed the
    # displayfd output, or two Xvfbs somehow bound the same socket.
    vds = [_track(tracked, VirtualDisplay()) for _ in range(N)]

    displays = [vd.get() for vd in vds]

    for d in displays:
        assert DISPLAY_RE.match(d), d

    unique: Set[str] = set(displays)
    assert len(unique) == len(displays), (
        f"duplicate displays: {len(displays) - len(unique)} of {len(displays)}"
    )

    # Every Xvfb is alive.
    for vd in vds:
        assert vd.proc is not None and vd.proc.poll() is None

    # Tear them all down and confirm every Xvfb actually exited -- no
    # leaked processes.
    for vd in vds:
        vd.kill()
    for vd in vds:
        _wait_for_exit(vd)
    for vd in vds:
        assert vd.proc is None or vd.proc.poll() is not None


def test_released_display_numbers_can_be_reused_on_the_next_launch(tracked):
    a = _track(tracked, VirtualDisplay())
    a_display = a.get()

    a.kill()
    _wait_for_exit(a)

    # Spawning a new Xvfb after release must succeed. The new display
    # number may or may not equal a_display -- Xvfb's allocation order is
    # its concern -- but we must get *some* display.
    b = _track(tracked, VirtualDisplay())
    b_display = b.get()
    assert DISPLAY_RE.match(b_display), b_display

    b.kill()
    _wait_for_exit(b)

    # Sanity: a_display was a valid form too.
    assert DISPLAY_RE.match(a_display), a_display


def _alive(pid: int) -> bool:
    """True while `pid` runs; a zombie waiting for its new parent counts as dead."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    # ProcessLookupError: reaped between open() and read(), which is how a
    # zombie's /proc entry goes away under a reader.
    except (FileNotFoundError, ProcessLookupError):
        return False


def test_xvfb_dies_with_the_process_that_started_it():
    """A SIGKILLed launcher never runs kill(), so the kernel must stop Xvfb (#868).

    Supervisors, `timeout` and CI cancellation end the Python process with a
    signal that skips every `finally`. Xvfb then has to go on its own, and
    remove its lock and socket on the way out.
    """
    child = subprocess.Popen(  # nosec
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "from camoufox.virtdisplay import VirtualDisplay\n"
            "vd = VirtualDisplay()\n"
            "print(vd.get()[1:], vd.proc.pid, flush=True)\n"
            "time.sleep(60)\n",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    display, pid = child.stdout.readline().split()
    xvfb = int(pid)
    assert _alive(xvfb)

    child.send_signal(signal.SIGKILL)
    child.wait()

    deadline = time.monotonic() + 5
    # Judged on the loop's last reading: once it sees a zombie, its new parent
    # is about to reap it, and a second /proc read lands in that reap.
    while (alive := _alive(xvfb)) and time.monotonic() < deadline:
        time.sleep(0.025)
    assert not alive, f"Xvfb {xvfb} outlived the process that started it"
    assert not os.path.exists(f"/tmp/.X{display}-lock")
    assert not os.path.exists(f"/tmp/.X11-unix/X{display}")
