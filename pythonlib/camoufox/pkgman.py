import os
import platform
import re
import shlex
import shutil
import sys
import tempfile
from dataclasses import dataclass
from functools import total_ordering
from io import BufferedWriter, BytesIO
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from zipfile import ZipFile

import click
import orjson
import requests
from platformdirs import user_cache_dir
from tqdm import tqdm
from typing_extensions import TypeAlias
from yaml import CLoader, load

from .__version__ import CONSTRAINTS
from .exceptions import (
    CamoufoxNotInstalled,
    UnsupportedArchitecture,
    UnsupportedOS,
    UnsupportedVersion,
)

DownloadBuffer: TypeAlias = Union[BytesIO, tempfile._TemporaryFileWrapper, BufferedWriter]

# Map machine architecture to Camoufox binary name
ARCH_MAP: Dict[str, str] = {
    'amd64': 'x86_64',
    'x86_64': 'x86_64',
    'x86': 'x86_64',
    'i686': 'i686',
    'i386': 'i686',
    'arm64': 'arm64',
    'aarch64': 'arm64',
    'armv5l': 'arm64',
    'armv6l': 'arm64',
    'armv7l': 'arm64',
}
OS_MAP: Dict[str, Literal['mac', 'win', 'lin']] = {'darwin': 'mac', 'linux': 'lin', 'win32': 'win'}

if sys.platform not in OS_MAP:
    raise UnsupportedOS(f"OS {sys.platform} is not supported")

OS_NAME: Literal['mac', 'win', 'lin'] = OS_MAP[sys.platform]

INSTALL_DIR: Path = Path(user_cache_dir("camoufox"))
LOCAL_DATA: Path = Path(os.path.abspath(__file__)).parent

# The supported architectures for each OS
OS_ARCH_MATRIX: Dict[str, List[str]] = {
    'mac': ['x86_64', 'arm64'],
    'win': ['x86_64', 'i686'],
    'lin': ['x86_64', 'arm64', 'i686'],
}

# The relative path to the camoufox executable
LAUNCH_FILE = {
    'win': 'camoufox.exe',
    'lin': 'camoufox-bin',
    'mac': '../MacOS/camoufox',
}


def rprint(*a, **k):
    click.secho(*a, **k, bold=True)


@total_ordering
@dataclass
class Version:
    """
    A version string that can be compared to other version strings.
    Stores versions up to 5 parts.
    """

    release: str
    version: Optional[str] = None

    def __post_init__(self) -> None:
        # Build an internal sortable structure
        self.sorted_rel = tuple(
            [
                *(int(x) if x.isdigit() else ord(x[0]) - 1024 for x in self.release.split('.')),
                *(0 for _ in range(5 - self.release.count('.'))),
            ]
        )

    @property
    def full_string(self) -> str:
        return f"{self.version}-{self.release}"

    def __eq__(self, other) -> bool:
        return self.sorted_rel == other.sorted_rel

    def __lt__(self, other) -> bool:
        return self.sorted_rel < other.sorted_rel

    def is_supported(self) -> bool:
        return VERSION_MIN <= self < VERSION_MAX

    @staticmethod
    def from_path(path: Optional[Path] = None) -> 'Version':
        """
        Get the version from the given path.
        """
        version_path = (path or INSTALL_DIR) / 'version.json'
        if not os.path.exists(version_path):
            raise FileNotFoundError(
                f"Version information not found at {version_path}. "
                "Please run `camoufox fetch` to install."
            )
        with open(version_path, 'rb') as f:
            version_data = orjson.loads(f.read())
            return Version(**version_data)

    @staticmethod
    def is_supported_path(path: Path) -> bool:
        """
        Check if the version at the given path is supported.
        """
        return Version.from_path(path) >= VERSION_MIN

    @staticmethod
    def build_minmax() -> Tuple['Version', 'Version']:
        return Version(release=CONSTRAINTS.MIN_VERSION), Version(release=CONSTRAINTS.MAX_VERSION)


# The minimum and maximum supported versions
VERSION_MIN, VERSION_MAX = Version.build_minmax()


class CamoufoxFetcher:
    """
    Handles fetching and installing the latest version of Camoufox.
    """

    def __init__(self) -> None:
        self.arch = self.get_platform_arch()
        self._version_obj: Optional[Version] = None
        self.pattern: re.Pattern = re.compile(
            rf'camoufox-(?P<version>.+)-(?P<release>.+)-{OS_NAME}\.{self.arch}\.zip'
        )

        self.fetch_latest()

    @staticmethod
    def get_platform_arch() -> str:
        """
        Get the current platform and architecture information.

        Returns:
            str: The architecture of the current platform

        Raises:
            UnsupportedArchitecture: If the current architecture is not supported
        """

        # Check if the architecture is supported for the OS
        plat_arch = platform.machine().lower()
        if plat_arch not in ARCH_MAP:
            raise UnsupportedArchitecture(f"Architecture {plat_arch} is not supported")

        arch = ARCH_MAP[plat_arch]

        # Check if the architecture is supported for the OS
        if arch not in OS_ARCH_MATRIX[OS_NAME]:
            raise UnsupportedArchitecture(f"Architecture {arch} is not supported for {OS_NAME}")

        return arch

    def find_release(self, releases: List[Dict]) -> Optional[Tuple[Version, str]]:
        """
        Finds the latest release from a GitHub releases API response that
        supports the Camoufox version constraints, the OS, and architecture.

        Returns:
            Optional[Tuple[Version, str]]: The version and URL of a release
        """
        # Search through releases for the first supported version
        for release in releases:
            for asset in release['assets']:
                match = self.pattern.match(asset['name'])
                if not match:
                    continue

                # Check if the version is supported
                version = Version(release=match['release'], version=match['version'])
                if not version.is_supported():
                    continue

                # Asset was found. Return data
                return version, asset['browser_download_url']
        return None

    def fetch_latest(self) -> None:
        """
        Fetch the URL of the latest camoufox release for the current platform.
        Sets the version, release, and url properties.

        Raises:
            requests.RequestException: If there's an error fetching release data
            ValueError: If no matching release is found for the current platform
        """
        api_url = "https://api.github.com/repos/daijro/camoufox/releases"
        resp = requests.get(api_url, timeout=20)
        resp.raise_for_status()

        # Find a release that fits the constraints
        releases = resp.json()
        release_data = self.find_release(releases)

        if release_data is None:
            raise UnsupportedVersion(
                f"No matching release found for {OS_NAME} {self.arch} in the "
                f"supported range: ({CONSTRAINTS.as_range()}). "
                "Please update the Python library."
            )

        # Set the version and URL
        self._version_obj, self._url = release_data

    @staticmethod
    def download_file(file: DownloadBuffer, url: str) -> DownloadBuffer:
        """
        Download a file from the given URL and return it as BytesIO.

        Args:
            url (str): The URL to download the file from

        Returns:
            DownloadBuffer: The downloaded file content as a BytesIO object
        """
        rprint(f'Downloading package: {url}')
        return webdl(url, buffer=file)

    def extract_zip(self, zip_file: DownloadBuffer) -> None:
        """
        Extract the contents of a zip file to the installation directory.

        Args:
            zip_file (DownloadBuffer): The zip file content as a BytesIO object
        """
        rprint(f'Extracting Camoufox: {INSTALL_DIR}')
        unzip(zip_file, str(INSTALL_DIR))

    @staticmethod
    def cleanup() -> bool:
        """
        Clean up the old installation.
        """
        if INSTALL_DIR.exists():
            rprint(f'Cleaning up cache: {INSTALL_DIR}')
            shutil.rmtree(INSTALL_DIR)
            return True
        return False

    def set_version(self) -> None:
        """
        Set the version in the INSTALL_DIR/version.json file
        """
        with open(INSTALL_DIR / 'version.json', 'wb') as f:
            f.write(orjson.dumps({'version': self.version, 'release': self.release}))

    def install(self) -> None:
        """
        Download and install the latest version of camoufox.

        Raises:
            Exception: If any error occurs during the installation process
        """
        # Clean up old installation
        self.cleanup()
        try:
            # Install to directory
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)

            # Fetch the latest zip
            with tempfile.NamedTemporaryFile() as temp_file:
                self.download_file(temp_file, self.url)
                self.extract_zip(temp_file)
                self.set_version()

            # Set permissions on INSTALL_DIR
            if OS_NAME != 'win':
                os.system(f'chmod -R 755 {shlex.quote(str(INSTALL_DIR))}')  # nosec

            rprint('\nCamoufox successfully installed.', fg="yellow")
        except Exception as e:
            rprint(f"Error installing Camoufox: {str(e)}")
            self.cleanup()
            raise

    @property
    def url(self) -> str:
        """
        Url of the fetched latest version of camoufox.

        Returns:
            str: The version of the installed camoufox

        Raises:
            ValueError: If the version is not available (fetch_latest not ran)
        """
        if self._url is None:
            raise ValueError("Url is not available. Make sure to run fetch_latest first.")
        return self._url

    @property
    def version(self) -> str:
        """
        Version of the fetched latest version of camoufox.

        Returns:
            str: The version of the installed camoufox

        Raises:
            ValueError: If the version is not available (fetch_latest not ran)
        """
        if self._version_obj is None or not self._version_obj.version:
            raise ValueError("Version is not available. Make sure to run the fetch_latest first.")

        return self._version_obj.version

    @property
    def release(self) -> str:
        """
        Release of the fetched latest version of camoufox.

        Returns:
            str: The release of the installed camoufox

        Raises:
            ValueError: If the release information is not available (fetch_latest not ran)
        """
        if self._version_obj is None:
            raise ValueError(
                "Release information is not available. Make sure to run the installation first."
            )

        return self._version_obj.release

    @property
    def verstr(self) -> str:
        """
        Fetches the version and release in version-release format

        Returns:
            str: The version of the installed camoufox
        """
        if self._version_obj is None:
            raise ValueError("Version is not available. Make sure to run the installation first.")
        return self._version_obj.full_string


def installed_verstr() -> str:
    """
    Get the full version string of the installed camoufox.
    """
    return Version.from_path().full_string


def camoufox_path(download_if_missing: bool = True) -> Path:
    """
    Full path to the camoufox folder.
    """

    # Ensure the directory exists and is not empty
    if not os.path.exists(INSTALL_DIR) or not os.listdir(INSTALL_DIR):
        if not download_if_missing:
            raise FileNotFoundError(f"Camoufox executable not found at {INSTALL_DIR}")

    # Camoufox exists and the the version is supported
    elif os.path.exists(INSTALL_DIR) and Version.from_path().is_supported():
        return INSTALL_DIR

    # Ensure the version is supported
    else:
        if not download_if_missing:
            raise UnsupportedVersion("Camoufox executable is outdated.")

    # Install and recheck
    CamoufoxFetcher().install()
    return camoufox_path()


def get_path(file: str) -> str:
    """
    Get the path to the camoufox executable.
    """
    if OS_NAME == 'mac':
        return os.path.abspath(camoufox_path() / 'Camoufox.app' / 'Contents' / 'Resources' / file)
    return str(camoufox_path() / file)


def launch_path() -> str:
    """
    Get the path to the camoufox executable.
    """
    launch_path = get_path(LAUNCH_FILE[OS_NAME])
    if not os.path.exists(launch_path):
        # Not installed error
        raise CamoufoxNotInstalled(
            f"Camoufox is not installed at {camoufox_path()}. Please run `camoufox fetch` to install."
        )
    return launch_path


def webdl(
    url: str,
    desc: Optional[str] = None,
    buffer: Optional[DownloadBuffer] = None,
    bar: bool = True,
) -> DownloadBuffer:
    """
    Download a file from the given URL and return it as BytesIO.

    Args:
        url (str): The URL to download the file from
        buffer (Optional[BytesIO]): A BytesIO object to store the downloaded file
        bar (bool): Whether to show the progress bar

    Returns:
        DownloadBuffer: The downloaded file content as a BytesIO object

    Raises:
        requests.RequestException: If there's an error downloading the file
    """
    response = requests.get(url, stream=True)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    block_size = 8192
    if buffer is None:
        buffer = BytesIO()

    with tqdm(
        total=total_size,
        unit='iB',
        bar_format=None if bar else '{desc}: {percentage:3.0f}%',
        unit_scale=True,
        desc=desc,
    ) as progress_bar:
        for data in response.iter_content(block_size):
            size = buffer.write(data)
            progress_bar.update(size)

    buffer.seek(0)
    return buffer


def unzip(
    zip_file: DownloadBuffer,
    extract_path: str,
    desc: Optional[str] = None,
    bar: bool = True,
) -> None:
    """
    Extract the contents of a zip file to the installation directory.

    Args:
        zip_file (BytesIO): The zip file content as a BytesIO object

    Raises:
        zipfile.BadZipFile: If the zip file is invalid or corrupted
        OSError: If there's an error creating directories or writing files
    """
    with ZipFile(zip_file) as zf:
        for member in tqdm(
            zf.infolist(), desc=desc, bar_format=None if bar else '{desc}: {percentage:3.0f}%'
        ):
            zf.extract(member, extract_path)


def load_yaml(file: str) -> Dict[str, Any]:
    """
    Loads a local YAML file and returns it as a dictionary.
    """
    with open(LOCAL_DATA / file, 'r') as f:
        return load(f, Loader=CLoader)
