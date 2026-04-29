"""
Tests for camoufox.virtdisplay.

Mirrors camoufox-js/test/virtdisplay.test.ts.

Run with:
    cd pythonlib && python -m pytest tests/test_virtdisplay.py -v

VIRTDISPLAY_TEST_N controls the concurrent-launch count. Default is kept
low so the test passes on any developer box; set to e.g. 1000 to exercise
real scaling. At high N you will need `ulimit -n` headroom -- each Xvfb
takes one X11 socket plus our -displayfd pipe.
"""

import os
import re
import sys
import time
from typing import List, Set

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.virtdisplay import VirtualDisplay  # noqa: E402

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
    assert vd.proc.poll() is not None  # exited


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
        assert vd.proc.poll() is not None


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
