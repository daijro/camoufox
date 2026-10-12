"""Unit tests for the camoufox pipe-liveness watchdog (PR against #719).

No real browser needed: the probe path is exercised against a fake browser whose
new_context() either returns instantly or hangs forever. Fault-injecting a real dead
Juggler pipe without C++ help is not feasible — covered honestly in the PR body.
"""

import asyncio
import threading
import time

import pytest

from camoufox.exceptions import JugglerPipeTimeout
from camoufox.watchdog import PipeWatchdog, watchdog_from


class FakeBrowser:
    """Minimal browser stand-in for the probe path."""

    def __init__(self, *, hang_new_context: bool = False):
        self.hang = hang_new_context
        self.contexts_opened = 0

    async def new_context(self):
        self.contexts_opened += 1
        if self.hang:
            await asyncio.sleep(3600)
        return FakeContext()


class FakeContext:
    async def close(self):
        return None


@pytest.fixture
def bg_loop():
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    th.join(timeout=5)
    loop.close()


def test_watchdog_from_accepts_true_and_dict():
    assert watchdog_from(True) == {
        "interval": 60, "timeout": 30, "on_dead": None, "stop_on_dead": True
    }
    merged = watchdog_from({"interval": 5, "on_dead": lambda b, e: None})
    assert merged["interval"] == 5 and merged["timeout"] == 30
    with pytest.raises(ValueError):
        watchdog_from({"bogus": 1})
    with pytest.raises(TypeError):
        watchdog_from(42)


def test_probe_ok(bg_loop):
    fb = FakeBrowser()
    wd = PipeWatchdog(fb, bg_loop, {"interval": 0.05, "timeout": 2})
    t0 = time.monotonic()
    wd._probe_once(2)
    assert time.monotonic() - t0 < 1
    assert fb.contexts_opened == 1


def test_probe_hang_raises_typed(bg_loop):
    fb = FakeBrowser(hang_new_context=True)
    wd = PipeWatchdog(fb, bg_loop, {"interval": 0.05, "timeout": 0.2})
    with pytest.raises(JugglerPipeTimeout):
        wd._probe_once(0.2)
    assert issubclass(JugglerPipeTimeout, TimeoutError)


def test_thread_fires_callback_and_stops(bg_loop):
    fb = FakeBrowser(hang_new_context=True)
    fired = []
    wd = PipeWatchdog(
        fb, bg_loop,
        {"interval": 0.05, "timeout": 0.2, "stop_on_dead": True,
         "on_dead": lambda b, e: fired.append((b, e))},
    )
    wd.start()
    wd.stop(timeout=5)
    assert fired and fired[0][0] is fb
    assert isinstance(fired[0][1], JugglerPipeTimeout)
    assert wd._thread is None
