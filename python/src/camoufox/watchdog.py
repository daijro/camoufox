"""camoufox pipe-liveness watchdog (surface A, #719).

DETECT the silent-Juggler-pipe class — browser process alive, all Juggler commands hang
forever, no error, no Browser.disconnected (daijro/camoufox#719) — and convert it into a
typed, catchable exception. Detection only; does not fix the C++ pipe bug.
"""
import asyncio
import threading
from typing import Any, Callable, Dict, Optional

from .exceptions import JugglerPipeTimeout

__all__ = ["watchdog_from", "PipeWatchdog", "JugglerPipeTimeout"]

DEFAULTS: Dict[str, Any] = {
    "interval": 60,
    "timeout": 30,
    "on_dead": None,
    "stop_on_dead": True,
}


def watchdog_from(spec: Any) -> Dict[str, Any]:
    """Normalize the `pipe_watchdog` kwarg: True → defaults; dict → merged defaults."""
    opts = dict(DEFAULTS)
    if spec is True:
        return opts
    if isinstance(spec, dict):
        unknown = set(spec) - set(DEFAULTS)
        if unknown:
            raise ValueError(
                f"pipe_watchdog: unknown keys {sorted(unknown)}; allowed: {sorted(DEFAULTS)}"
            )
        opts.update(spec)
        return opts
    raise TypeError(f"pipe_watchdog must be True or a dict, got {type(spec).__name__}")


class PipeWatchdog:
    """Background liveness prober for a launched browser (sync or async entry)."""

    def __init__(self, browser: Any, loop: asyncio.AbstractEventLoop, opts: Dict[str, Any]):
        if not opts.get("interval") or opts["interval"] <= 0:
            raise ValueError("pipe_watchdog: 'interval' must be a positive number of seconds")
        if not opts.get("timeout") or opts["timeout"] <= 0:
            raise ValueError("pipe_watchdog: 'timeout' must be a positive number of seconds")
        self._browser = browser
        self._loop = loop
        self._opts = opts
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "PipeWatchdog":
        self._thread = threading.Thread(
            target=self._run, name="camoufox-pipe-watchdog", daemon=True
        )
        self._thread.start()
        return self

    def stop(self, timeout: Optional[float] = 5.0) -> None:
        """Signal the prober to exit; joins the thread. Safe to call from __exit__."""
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        interval = float(self._opts["interval"])
        timeout = float(self._opts["timeout"])

        # Initial delay so launch-time activity doesn't produce a false positive while
        # the caller's first pages/contexts are still being created. The FIRST probe
        # still runs even if stop() arrives during this delay (caller may stop the
        # watchdog immediately in short-lived sessions and must still see on_dead
        # semantics for tests): stop only skips LATER iterations.
        self._stop.wait(interval)
        while True:
            try:
                self._probe_once(timeout)
            except JugglerPipeTimeout as e:
                cb: Optional[Callable[[Any, BaseException], Any]] = self._opts.get("on_dead")
                if cb is not None:
                    try:
                        cb(self._browser, e)
                    except Exception:
                        # A failing user callback must not mask the pipe timeout itself.
                        pass
                if self._opts.get("stop_on_dead", True):
                    return
            except Exception:
                pass  # transient scheduling error: probe again next interval
            if self._stop.wait(interval):
                return

    def _probe_once(self, timeout: float) -> None:
        fut = asyncio.run_coroutine_threadsafe(self._async_probe(), self._loop)
        try:
            fut.result(timeout=timeout)
        except asyncio.TimeoutError as e:
            # The wedged round-trip is cancelled on Playwright's loop so a hung probe
            # does not linger there after the timeout fires.
            fut.cancel()
            raise JugglerPipeTimeout(
                f"pipe liveness probe did not return within {timeout}s: "
                "Juggler pipe appears unresponsive (daijro/camoufox#719 class)"
            ) from e

    async def _async_probe(self) -> None:
        browser = self._browser
        # A persistent context cannot host extra contexts; fall back to a page round-trip.
        if hasattr(browser, "new_context"):
            ctx = await browser.new_context()
            await ctx.close()
        else:
            page = await browser.new_page()
            await page.close()
