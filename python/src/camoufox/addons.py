import os
from enum import Enum
from pathlib import Path
from typing import List, Optional, Union

from ._warnings import WARNINGS_DATA, _warn_from_caller
from .exceptions import InvalidAddonPath
from .pkgman import build_file


class DefaultAddons(Enum):
    """
    Default addons. Each browser release bundles them, extracted, under
    addons/<name>/ beside its binary (browser/scripts/fetch-ubo.py).
    """

    UBO = 'UBO'


def confirm_paths(paths: List[str]) -> None:
    """
    Confirms that the addon paths are valid
    """
    for path in paths:
        if not os.path.isdir(path):
            raise InvalidAddonPath(path)
        if not os.path.exists(os.path.join(path, 'manifest.json')):
            raise InvalidAddonPath(
                'manifest.json is missing. Addon path must be a path to an extracted addon.'
            )


def get_addon_path(addon_name: str, executable_path: Union[str, Path]) -> str:
    """
    Returns the path to the addon the build at executable_path bundles.
    """
    return str(build_file(executable_path, os.path.join('addons', addon_name)))


def add_default_addons(
    addons_list: List[str],
    exclude_list: Optional[List[DefaultAddons]],
    executable_path: Union[str, Path],
) -> None:
    """
    Adds the default addons the build at executable_path bundles, minus any
    specified in exclude_list, to addons_list
    """
    for addon in DefaultAddons:
        if addon in (exclude_list or []):
            continue
        path = get_addon_path(addon.name, executable_path)
        # A build released before the addons were bundled, or an unpackaged
        # one, has none. It still launches, but not as the browser asked for.
        if not os.path.exists(os.path.join(path, 'manifest.json')):
            _warn_from_caller(
                WARNINGS_DATA['addon_not_bundled'].format(addon=addon.name, path=path),
                RuntimeWarning,
            )
            continue
        addons_list.append(path)
