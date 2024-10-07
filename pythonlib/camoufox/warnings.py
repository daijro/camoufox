import inspect
import warnings
from pathlib import Path
from typing import Optional

from camoufox.pkgman import load_yaml

WARNINGS_DATA = load_yaml('warnings.yml')


class LeakWarning(RuntimeWarning):
    """
    Raised when a the user has a setting enabled that can cause detection.
    """

    @staticmethod
    def warn(warning_key: str, i_know_what_im_doing: Optional[bool] = None) -> None:
        """
        Warns the user if a passed parameter can cause leaks.
        """
        warning = WARNINGS_DATA[warning_key]
        if i_know_what_im_doing:
            return
        if i_know_what_im_doing is not None:
            warning += '\nIf this is intentional, pass `i_know_what_im_doing=True`.'

        # Get caller information
        current_module = Path(__file__).parent
        frame = inspect.currentframe()
        while frame:
            if not Path(frame.f_code.co_filename).is_relative_to(current_module):
                break
            frame = frame.f_back

        if frame:
            warnings.warn_explicit(
                warning,
                category=LeakWarning,
                filename=frame.f_code.co_filename,
                lineno=frame.f_lineno,
            )
            return

        warnings.warn(warning, category=LeakWarning)
