import os
from multiprocessing import Lock
from typing import List, Optional

from .addons import DefaultAddons
from .pkgman import get_path, unzip, webdl


def add_default_addons(
    addons_list: List[str], exclude_list: Optional[List[DefaultAddons]] = None
) -> None:
    """
    Adds default addons, minus any specified in exclude_list, to addons_list
    """
    # Build a dictionary from DefaultAddons, excluding keys found in exclude_list
    if exclude_list is None:
        exclude_list = []

    addons = [addon for addon in DefaultAddons if addon not in exclude_list]

    with Lock():
        maybe_download_addons(addons, addons_list)


def download_and_extract(url: str, extract_path: str, name: str) -> None:
    """
    Downloads and extracts an addon from a given URL to a specified path
    """
    # Create a temporary file to store the downloaded zip
    buffer = webdl(url, desc=f"Downloading addon ({name})", bar=False)
    unzip(buffer, extract_path, f"Extracting addon ({name})", bar=False)


def get_addon_path(addon_name: str) -> str:
    """
    Returns a path to the addon
    """
    return get_path(os.path.join("addons", addon_name))


def maybe_download_addons(
    addons: List[DefaultAddons], addons_list: Optional[List[str]] = None
) -> None:
    """
    Downloads and extracts addons from a given dictionary to a specified list
    Skips downloading if the addon is already downloaded
    """
    for addon in addons:
        # Get the addon path
        addon_path = get_addon_path(addon.name)

        # Check if the addon is already extracted
        if os.path.exists(addon_path):
            # Add the existing addon path to addons_list
            if addons_list is not None:
                addons_list.append(addon_path)
            continue

        # Addon doesn't exist, create directory and download
        try:
            os.makedirs(addon_path, exist_ok=True)
            download_and_extract(addon.value, addon_path, addon.name)
            # Add the new addon directory path to addons_list
            if addons_list is not None:
                addons_list.append(addon_path)
        except Exception as e:
            print(f"Failed to download and extract {addon.name}: {e}")
