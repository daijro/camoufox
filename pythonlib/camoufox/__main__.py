"""
CLI package manager for Camoufox.

Adapted from https://github.com/daijro/hrequests/blob/main/hrequests/__main__.py
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from os import environ
from typing import Optional

import click

from .addons import DefaultAddons
from .locale import ALLOW_GEOIP, download_mmdb, remove_mmdb
from .pkgman import INSTALL_DIR, CamoufoxFetcher, installed_verstr, rprint
from .xpi_dl import maybe_download_addons

try:
    from browserforge.download import download as update_browserforge
except ImportError:
    # Account for other Browserforge versions
    from browserforge.download import Download as update_browserforge


class CamoufoxUpdate(CamoufoxFetcher):
    """
    Checks & updates Camoufox
    """

    def __init__(self) -> None:
        """
        Initializes the CamoufoxUpdate class
        """
        super().__init__()
        self.current_verstr: Optional[str]
        try:
            self.current_verstr = installed_verstr()
        except FileNotFoundError:
            self.current_verstr = None

    def is_updated_needed(self) -> bool:
        # Camoufox is not installed
        if self.current_verstr is None:
            return True
        # If the installed version is not the latest version
        if self.current_verstr != self.verstr:
            return True
        return False

    def update(self) -> None:
        """
        Updates Camoufox if needed
        """
        # Check if the version is the same as the latest available version
        if not self.is_updated_needed():
            rprint("Camoufox binaries up to date!", fg="green")
            rprint(f"Current version: v{self.current_verstr}", fg="green")
            return

        # Download updated file
        if self.current_verstr is not None:
            # Display an updating message
            rprint(
                f"Updating Camoufox binaries from v{self.current_verstr} => v{self.verstr}",
                fg="yellow",
            )
        else:
            rprint(f"Fetching Camoufox binaries v{self.verstr}...", fg="yellow")
        # Install the new version
        self.install()


@click.group()
def cli() -> None:
    pass


@cli.command(name='fetch')
@click.option(
    '--browserforge', is_flag=True, help='Update browserforge\'s header and fingerprint definitions'
)
def fetch(browserforge=False) -> None:
    """
    Fetch the latest version of Camoufox and optionally update Browserforge's database
    """
    CamoufoxUpdate().update()
    # Fetch the GeoIP database
    if ALLOW_GEOIP:
        download_mmdb()

    # Download default addons
    maybe_download_addons(list(DefaultAddons))

    if browserforge:
        update_browserforge(headers=True, fingerprints=True)


@cli.command(name='remove')
def remove() -> None:
    """
    Remove all downloaded files
    """
    if not CamoufoxUpdate().cleanup():
        rprint("Camoufox binaries not found!", fg="red")
    # Remove the GeoIP database
    remove_mmdb()


@cli.command(name='test')
@click.argument('url', default=None, required=False)
def test(url: Optional[str] = None) -> None:
    """
    Open the Playwright inspector
    """
    from .sync_api import Camoufox

    with Camoufox(headless=False, env=environ) as browser:
        page = browser.new_page()
        if url:
            page.goto(url)
        page.pause()  # Open the Playwright inspector


@cli.command(name='server')
def server() -> None:
    """
    Launch a Playwright server
    """
    from .server import launch_server

    launch_server()


@cli.command(name='path')
def path() -> None:
    """
    Display the path to the Camoufox executable
    """
    rprint(INSTALL_DIR, fg="green")


@cli.command(name='version')
def version() -> None:
    """
    Display the current version
    """
    # python package version
    try:
        rprint(f"Pip package:\tv{pkg_version('camoufox')}", fg="green")
    except PackageNotFoundError:
        rprint("Pip package:\tNot installed!", fg="red")

    updater = CamoufoxUpdate()
    bin_ver = updater.current_verstr

    # If binaries are not downloaded
    if not bin_ver:
        rprint("Camoufox:\tNot downloaded!", fg="red")
        return
    # Print the base version
    rprint(f"Camoufox:\tv{bin_ver} ", fg="green", nl=False)

    # Check for Camoufox updates
    if updater.is_updated_needed():
        rprint(f"(Latest supported: v{updater.verstr})", fg="red")
    else:
        rprint("(Up to date!)", fg="yellow")


if __name__ == '__main__':
    cli()
