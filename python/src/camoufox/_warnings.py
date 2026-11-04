import inspect
import platform
import warnings
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional, Type

from camoufox.pkgman import load_yaml

WARNINGS_DATA = load_yaml('warnings.yml')


def _warn_from_caller(message: str, category: Type[Warning]) -> None:
    """Attribute the warning to the first frame outside this package, so it
    points at the user's call rather than at camoufox internals."""
    current_module = Path(__file__).parent
    frame = inspect.currentframe()
    while frame:
        if not Path(frame.f_code.co_filename).is_relative_to(current_module):
            break
        frame = frame.f_back

    if frame:
        warnings.warn_explicit(
            message,
            category=category,
            filename=frame.f_code.co_filename,
            lineno=frame.f_lineno,
        )
        return

    warnings.warn(message, category=category)


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
        _warn_from_caller(warning, LeakWarning)


def _browser_version() -> str:
    from camoufox.exceptions import CamoufoxNotInstalled
    from camoufox.pkgman import installed_verstr

    try:
        return installed_verstr()
    except CamoufoxNotInstalled:
        return 'not installed'


class FallbackWarning(RuntimeWarning):
    """
    Raised when part of an identity could not be drawn and a substitute was used.
    """

    @staticmethod
    def warn(what: str, instead: str, error: Exception, identity: Optional[str] = None) -> None:
        """
        Warns that `what` failed with `error` and the identity uses `instead`,
        with a block of versions and the error for the user to paste into an issue.
        """
        try:
            camoufox_version = version('camoufox')
        except PackageNotFoundError:
            camoufox_version = 'source checkout'
        lines = [
            f'camoufox: {camoufox_version}',
            f'browser: {_browser_version()}',
            f'os: {platform.platform()}',
            f'python: {platform.python_version()}',
            f'error: {type(error).__name__}: {error}',
        ]
        if identity:
            lines.append(f'identity: {identity}')
        report = '\n'.join(f'    {line}' for line in lines)
        _warn_from_caller(
            WARNINGS_DATA['fallback'].format(what=what, instead=instead, report=report),
            FallbackWarning,
        )
