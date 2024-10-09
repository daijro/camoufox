import os
import subprocess  # nosec
from glob import glob
from shutil import which
from typing import List, Optional

from camoufox.exceptions import (
    CannotExecuteXvfb,
    CannotFindXvfb,
    VirtualDisplayNotSupported,
)
from camoufox.pkgman import OS_NAME


class VirtualDisplay:
    """
    A minimal virtual display implementation for Linux.
    """

    def __init__(self) -> None:
        """
        Constructor for the VirtualDisplay class (singleton object).
        """
        self.proc: Optional[subprocess.Popen] = None
        self._display: Optional[int] = None

    xvfb_args = (
        # fmt: off
        "-screen", "0", "1x1x8",
        "-ac",
        "-nolisten", "tcp",
        "-extension", "RENDER",
        "-extension", "GLX",
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
        """
        Get the path to the xvfb executable
        """
        path = which("Xvfb")
        if not path:
            raise CannotFindXvfb("Please install Xvfb to use headless mode.")
        if not os.access(path, os.X_OK):
            raise CannotExecuteXvfb(f"I do not have permission to execute Xvfb: {path}")
        return path

    @property
    def xvfb_cmd(self) -> List[str]:
        """
        Get the xvfb command
        """
        return [self.xvfb_path, f':{self.display}', *self.xvfb_args]

    def execute_xvfb_singleton(self, debug: Optional[bool] = False):
        """
        Spawn a detatched process
        """
        if debug:
            print('Starting virtual display:', ' '.join(self.xvfb_cmd))
        self.proc = subprocess.Popen(  # nosec
            self.xvfb_cmd,
            stdout=None if debug else subprocess.DEVNULL,
            stderr=None if debug else subprocess.DEVNULL,
        )

    def new_or_reuse(self, debug: Optional[bool] = False) -> str:
        """
        Get the display number
        """
        self.assert_linux()

        if self.proc is None:
            self.execute_xvfb_singleton(debug)
        elif debug:
            print(f'Using virtual display: {self.display}')
        return f':{self.display}'

    def __del__(self):
        """
        Terminate the xvfb process
        """
        if self.proc:
            self.proc.terminate()

    @staticmethod
    def _get_lock_files() -> List[str]:
        """
        Get list of lock files in /tmp
        """
        tmpd = os.environ.get('TMPDIR', '/tmp')  # nosec
        try:
            lock_files = glob(os.path.join(tmpd, ".X*-lock"))
        except FileNotFoundError:
            return []
        return [p for p in lock_files if os.path.isfile(p)]

    @staticmethod
    def _free_display() -> int:
        """
        Search for free display
        """
        ls = list(
            map(lambda x: int(x.split("X")[1].split("-")[0]), VirtualDisplay._get_lock_files())
        )
        return max(99, max(ls) + 3) if ls else 99

    @property
    def display(self) -> int:
        """
        Get the display number
        """
        if self._display is None:
            self._display = self._free_display()
        return self._display

    @staticmethod
    def assert_linux():
        """
        Assert that the current OS is Linux
        """
        if OS_NAME != 'lin':
            raise VirtualDisplayNotSupported("Virtual display is only supported on Linux.")


VIRTUAL_DISPLAY = VirtualDisplay()
