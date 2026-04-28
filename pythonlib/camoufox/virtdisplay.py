import glob
import os
import os.path
import random
import subprocess  # nosec
import tempfile
import time
from shutil import which
from typing import List, Optional

from camoufox.exceptions import (
    CannotExecuteXvfb,
    CannotFindXvfb,
    VirtualDisplayNotSupported,
)
from camoufox.pkgman import OS_NAME

# How long to wait for Xvfb to bind its X11 socket before giving up.
SOCKET_READY_TIMEOUT_S = 10.0
SOCKET_POLL_INTERVAL_S = 0.05


class VirtualDisplay:
    """A minimal virtual display implementation for Linux."""

    def __init__(self, debug: Optional[bool] = False) -> None:
        self.debug = debug
        self.proc: Optional[subprocess.Popen] = None
        self._display: Optional[int] = None
        self._claim_path_used: Optional[str] = None

    xvfb_args = (
        # fmt: off
        "-screen", "0", "1x1x24",
        "-ac",
        "-nolisten", "tcp",
        "-extension", "RENDER",
        "+extension", "GLX",
        "-extension", "COMPOSITE",
        "-extension", "XVideo",
        "-extension", "XVideo-MotionCompensation",
        "-extension", "XINERAMA",
        "-shmem",
        "-fp", "built-ins",
        "-nocursor",
        "-br",
        # fmt: on
    )

    @property
    def xvfb_path(self) -> str:
        path = which("Xvfb")
        if not path:
            raise CannotFindXvfb("Please install Xvfb to use headless mode.")
        if not os.access(path, os.X_OK):
            raise CannotExecuteXvfb(f"I do not have permission to execute Xvfb: {path}")
        return path

    def _xvfb_cmd(self, display: int) -> List[str]:
        return [self.xvfb_path, f':{display}', *self.xvfb_args]

    def _execute_xvfb(self, display: int) -> None:
        cmd = self._xvfb_cmd(display)
        if self.debug:
            print('Starting virtual display:', ' '.join(cmd))
        # Force Mesa software GLX to avoid the NVIDIA libGLvnd rwlock stall.
        env = {
            **os.environ,
            "__GLX_VENDOR_LIBRARY_NAME": "mesa",
            "LIBGL_ALWAYS_SOFTWARE": "1",
        }
        self.proc = subprocess.Popen(  # nosec
            cmd,
            stdout=None if self.debug else subprocess.DEVNULL,
            stderr=None if self.debug else subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )

    def get(self) -> str:
        self.assert_linux()

        if self.proc is None:
            display = VirtualDisplay._claim_display()
            self._display = display
            self._claim_path_used = VirtualDisplay._claim_path(display)
            self._execute_xvfb(display)
            self._wait_for_socket(display)
        elif self.debug:
            print(f'Using virtual display: {self._display}')

        return f':{self._display}'

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            if self.debug:
                print('Terminating virtual display:', self._display)
            self.proc.terminate()
        if self._claim_path_used:
            try:
                os.unlink(self._claim_path_used)
            except FileNotFoundError:
                pass
            self._claim_path_used = None

    def __del__(self):
        self.kill()

    def _wait_for_socket(self, display: int) -> None:
        """Poll for /tmp/.X11-unix/X<display>; Xvfb only creates it on a successful bind."""
        tmpd = os.environ.get("TMPDIR") or tempfile.gettempdir()
        socket_path = os.path.join(tmpd, ".X11-unix", f"X{display}")
        deadline = time.monotonic() + SOCKET_READY_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.proc is not None:
                rc = self.proc.poll()
                if rc is not None:
                    raise CannotExecuteXvfb(
                        f"Xvfb exited with code {rc} before binding display :{display}"
                    )
            if os.path.exists(socket_path):
                return
            time.sleep(SOCKET_POLL_INTERVAL_S)
        raise CannotExecuteXvfb(
            f"Xvfb did not bind display :{display} within {int(SOCKET_READY_TIMEOUT_S * 1000)}ms"
        )

    @staticmethod
    def _get_lock_files() -> List[str]:
        """Lock files Xvfb creates: /tmp/.X<N>-lock."""
        tmpd = os.environ.get("TMPDIR") or tempfile.gettempdir()
        try:
            return [
                p for p in glob.glob(os.path.join(tmpd, ".X*-lock"))
                if os.path.isfile(p)
            ]
        except OSError:
            return []

    @staticmethod
    def _claim_path(display: int) -> str:
        """Camoufox-private claim file path; distinct from Xvfb's .X<N>-lock."""
        tmpd = os.environ.get("TMPDIR") or tempfile.gettempdir()
        return os.path.join(tmpd, f".camoufox-X{display}.claim")

    # Grace period before treating an unreadable/empty claim as stale. There
    # is a brief window after O_EXCL|O_CREAT but before the owner writes its
    # PID; without this, a concurrent sweep would unlink a live claim.
    _CLAIM_GRACE_SECONDS = 5.0

    @staticmethod
    def _sweep_stale_claims() -> None:
        """Remove claim files whose owning PID is no longer alive."""
        tmpd = os.environ.get("TMPDIR") or tempfile.gettempdir()
        now = time.time()
        for path in glob.glob(os.path.join(tmpd, ".camoufox-X*.claim")):
            try:
                with open(path, "r") as f:
                    raw = f.read().strip()
                pid = int(raw)
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                # Unreadable or malformed. Could be a claim mid-creation by
                # another process; only sweep if it has been like this for
                # longer than the grace period.
                try:
                    age = now - os.path.getmtime(path)
                except OSError:
                    continue
                if age > VirtualDisplay._CLAIM_GRACE_SECONDS:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            except PermissionError:
                # PID exists but is owned by another user; leave it alone.
                pass

    @staticmethod
    def _claim_display() -> int:
        """Atomically reserve a display number across concurrent camoufox processes."""
        VirtualDisplay._sweep_stale_claims()

        ls: List[int] = []
        for x in VirtualDisplay._get_lock_files():
            try:
                ls.append(int(os.path.basename(x).split("X")[1].split("-")[0]))
            except (IndexError, ValueError):
                continue
        baseline = max([99, *ls]) if ls else 99
        tmpd = os.environ.get("TMPDIR") or tempfile.gettempdir()
        pid_bytes = f"{os.getpid()}\n".encode("ascii")

        for attempt in range(50):
            candidate = baseline + random.randint(3, 19) + attempt  # nosec
            # Skip if Xvfb already holds this display.
            if os.path.exists(os.path.join(tmpd, f".X{candidate}-lock")):
                continue
            claim_path = VirtualDisplay._claim_path(candidate)
            try:
                fd = os.open(
                    claim_path,
                    os.O_EXCL | os.O_CREAT | os.O_WRONLY,
                    0o644,
                )
            except FileExistsError:
                continue
            try:
                os.write(fd, pid_bytes)
            finally:
                os.close(fd)
            return candidate

        raise CannotExecuteXvfb("Could not reserve a free X11 display after 50 attempts")

    @staticmethod
    def assert_linux():
        if OS_NAME != 'lin':
            raise VirtualDisplayNotSupported("Virtual display is only supported on Linux.")
