import os
import select
import subprocess  # nosec
import time
from shutil import which
from typing import Optional

from camoufox.exceptions import (
    CannotExecuteXvfb,
    CannotFindXvfb,
    VirtualDisplayNotSupported,
)
from camoufox.pkgman import OS_NAME

# Safe timeout for Xvfb writing display num, prevents infinite hang.
DISPLAYFD_READ_TIMEOUT_S = 10.0


class VirtualDisplay:
    """A minimal virtual display implementation for Linux."""

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
        "-fp", "built-ins",
        "-nocursor",
        "-br",
        # fmt: on
    )

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self.proc: Optional[subprocess.Popen] = None
        self._display: Optional[int] = None

    @property
    def xvfb_path(self) -> str:
        path = which("Xvfb")
        if not path:
            raise CannotFindXvfb("Please install Xvfb to use headless mode.")
        if not os.access(path, os.X_OK):
            raise CannotExecuteXvfb(f"I do not have permission to execute Xvfb: {path}")
        return path

    def get(self) -> str:
        self._assert_linux()

        if self.proc is None:
            # Launch Xvfb with -displayfd so Xvfb itself picks a free display
            # number atomically and reports it back. Avoids userspace races.
            # subprocess.Popen's pass_fds keeps an fd at its parent number in
            # the child (unlike Node's `stdio: [..., 'pipe']` which renumbers
            # to 3), so we tell Xvfb that exact number.
            read_fd, write_fd = os.pipe()
            cmd = [self.xvfb_path, "-displayfd", str(write_fd), *self.xvfb_args]
            if self.debug:
                print("Starting virtual display:", " ".join(cmd))
            self.proc = subprocess.Popen(  # nosec
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=None if self.debug else subprocess.DEVNULL,
                stderr=None if self.debug else subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(write_fd,),
                env={
                    **os.environ,
                    # Force Mesa software GLX; we don't use the GPU anyway.
                    "__GLX_VENDOR_LIBRARY_NAME": "mesa",
                    "LIBGL_ALWAYS_SOFTWARE": "1",
                },
            )
            os.close(write_fd)  # so the read end EOFs when Xvfb closes its end

            buf = b""
            deadline = time.monotonic() + DISPLAYFD_READ_TIMEOUT_S
            try:
                while b"\n" not in buf:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([read_fd], [], [], remaining)[0]:
                        self.kill()
                        raise CannotExecuteXvfb(
                            f"Xvfb did not report a display within "
                            f"{int(DISPLAYFD_READ_TIMEOUT_S * 1000)}ms"
                        )
                    chunk = os.read(read_fd, 64)
                    if not chunk:
                        self.kill()
                        raise CannotExecuteXvfb(
                            f"Xvfb did not report a display "
                            f"(got {buf!r}, exit={self.proc.poll()})"
                        )
                    buf += chunk
            finally:
                os.close(read_fd)

            try:
                self._display = int(buf.strip())
            except ValueError:
                self.kill()
                raise CannotExecuteXvfb(f"Xvfb wrote non-integer display: {buf!r}")
        elif self.debug:
            print(f"Using virtual display: {self._display}")

        return f":{self._display}"

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            if self.debug:
                print("Terminating virtual display:", self._display)
            self.proc.terminate()

    @staticmethod
    def _assert_linux() -> None:
        if OS_NAME != "lin":
            raise VirtualDisplayNotSupported("Virtual display is only supported on Linux.")
