"""
CLI package manager for Camoufox
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from os import environ
from typing import Any, List, Optional, Tuple

import rich_click as click

from .addons import DefaultAddons, maybe_download_addons
from .geolocation import (
    ALLOW_GEOIP,
    GEOIP_DIR,
    _load_geoip_repos,
    download_mmdb,
    get_mmdb_path,
    load_geoip_config,
    remove_mmdb,
    save_geoip_config,
)
from .multiversion import (
    BROWSERS_DIR,
    CONFIG_FILE,
    REPO_CACHE_FILE,
    InstalledVersion,
    get_default_channel,
    list_installed,
    load_config,
    load_repo_cache,
    print_tree,
    remove_version,
    save_config,
    save_repo_cache,
    set_active,
)
from .pkgman import (
    INSTALL_DIR,
    AvailableVersion,
    CamoufoxFetcher,
    RepoConfig,
    installed_verstr,
    list_available_versions,
    rprint,
)


def _inquirer_select(
    choices: List[Tuple[str, Any]],
    message: str,
) -> Optional[Any]:
    """
    Generic inquirer selection. Returns selected value or None
    """
    import inquirer
    from inquirer.themes import GreenPassion

    try:
        result = inquirer.prompt(
            [inquirer.List('item', message=message, choices=choices, carousel=True)],
            theme=GreenPassion(),
        )
        return result['item'] if result else None
    except KeyboardInterrupt:
        return None


def _find_installed(specifier: str) -> Optional[InstalledVersion]:
    """
    Find installed version by channel path, build, or full version string
    """
    spec = specifier.lower()
    installed = list_installed()

    for v in installed:
        if any(
            [
                v.channel_path.lower() == spec,
                v.relative_path.lower() == spec,
                v.version.build.lower() == spec,
                v.version.full_string.lower() == spec,
            ]
        ):
            return v

    parts = spec.split('/')
    if len(parts) == 2:
        repo, ctype = parts
        is_pre = ctype == "prerelease"
        for v in installed:
            if v.repo_name == repo and v.is_prerelease == is_pre:
                return v

    return None


def _get_geoip_source_name() -> str:
    """
    Get the name of the active GeoIP source
    """
    try:
        return load_geoip_config().get('name', 'Default')
    except Exception:
        return "Default"


def _do_sync(spoof_os=None, spoof_arch=None) -> bool:
    """
    Sync available versions from remote repositories. Returns True on success
    """
    rprint("Syncing repositories...", fg="yellow")

    cache = {'repos': [], 'spoof_os': spoof_os, 'spoof_arch': spoof_arch}

    for repo_config in RepoConfig.load_repos():
        rprint(f"  {repo_config.name}...", fg="cyan", nl=False)
        try:
            versions = list_available_versions(
                repo_config=repo_config,
                include_prerelease=True,
                spoof_os=spoof_os,
                spoof_arch=spoof_arch,
            )
            repo_data = {
                'name': repo_config.name,
                'repo': repo_config.repo,
                'versions': [
                    {
                        'version': v.version.version,
                        'build': v.version.build,
                        'url': v.url,
                        'is_prerelease': v.is_prerelease,
                        'asset_id': v.asset_id,
                        'asset_size': v.asset_size,
                        'asset_updated_at': v.asset_updated_at,
                    }
                    for v in versions
                ],
            }
            cache['repos'].append(repo_data)
            rprint(f" {len(versions)} versions", fg="green")
        except Exception as e:
            rprint(f" Error: {e}", fg="red")

    save_repo_cache(cache)
    total = sum(len(r['versions']) for r in cache['repos'])
    platform_str = f" ({spoof_os}/{spoof_arch})" if spoof_os else ""
    rprint(f"\nSynced {total} versions from {len(cache['repos'])} repos{platform_str}.", fg="green")

    return True


def _ensure_synced() -> bool:
    """
    Ensure repo cache exists. Returns True if synced, False if not
    """
    if not REPO_CACHE_FILE.exists():
        rprint("No repo cache found. Run 'camoufox sync' first.", fg="red")
        return False
    return True


class CamoufoxUpdate(CamoufoxFetcher):
    """
    Checks & updates Camoufox
    """

    def __init__(
        self,
        repo_config: Optional[RepoConfig] = None,
        selected_version: Optional[AvailableVersion] = None,
    ) -> None:
        super().__init__(repo_config=repo_config, selected_version=selected_version)
        try:
            self.current_verstr = installed_verstr()
        except FileNotFoundError:
            self.current_verstr = None

    def is_updated_needed(self) -> bool:
        return self.current_verstr is None or self.current_verstr != self.verstr

    def update(self, replace: bool = False, i_know_what_im_doing: bool = False) -> None:
        if not self.is_updated_needed() and not replace:
            rprint("Camoufox binaries up to date!", fg="green")
            rprint(f"Current version: v{self.current_verstr}", fg="green")
            return

        if self.is_prerelease and not i_know_what_im_doing:
            rprint(f"Warning: v{self.verstr} is a prerelease version!", fg="yellow")
            if not click.confirm("Continue with prerelease installation?"):
                rprint("Installation cancelled.", fg="red")
                return

        action = "Installing" if self.current_verstr else "Fetching"
        rprint(f"{action} Camoufox v{self.verstr}...", fg="yellow")
        self.install(replace=replace)


@click.group()
def cli() -> None:
    pass


@cli.command(name='sync')
@click.option('--spoof-os', type=click.Choice(['auto', 'mac', 'win', 'lin']), help='Spoof OS (auto = native)')
@click.option(
    '--spoof-arch', type=click.Choice(['auto', 'x86_64', 'i686', 'arm64']), help='Spoof architecture (auto = native)'
)
def sync(spoof_os, spoof_arch):
    """
    Sync available versions from remote repositories.
    """
    if spoof_os == 'auto':
        spoof_os = None
    if spoof_arch == 'auto':
        spoof_arch = None
    _do_sync(spoof_os=spoof_os, spoof_arch=spoof_arch)


@cli.command(name='fetch')
@click.argument('version', default=None, required=False)
def fetch(version):
    """
    Install the active version, or a specific version.

    \b
    Examples:
      camoufox fetch                         # install active version
      camoufox fetch official/135.0-beta.25  # install specific version
    """
    _do_sync()

    cache = load_repo_cache()
    config = load_config()

    if version:
        if '/' not in version:
            rprint("Format: <repo>/<version>-<build> (e.g., official/135.0-beta.25)", fg="red")
            return
        repo_name, ver_str = version.split('/', 1)
        ver_str = ver_str.lstrip('v')
    elif config.get('pinned'):
        channel = config.get('channel', '')
        repo_name = channel.split('/')[0] if '/' in channel else channel
        ver_str = config['pinned']
    else:
        channel = config.get('channel') or get_default_channel()
        if '/' in channel:
            repo_name, ctype = channel.split('/', 1)
        else:
            repo_name, ctype = channel, 'stable'
        for repo_data in cache.get('repos', []):
            if repo_data['name'].lower() != repo_name.lower():
                continue
            versions = repo_data.get('versions', [])
            if ctype == 'prerelease':
                candidates = [v for v in versions if v.get('is_prerelease')]
            else:
                candidates = [v for v in versions if not v.get('is_prerelease')]
            if candidates:
                ver_str = f"{candidates[0]['version']}-{candidates[0]['build']}"
                break
        else:
            rprint(f"No versions found for channel '{channel}'.", fg="red")
            return

    for repo_data in cache.get('repos', []):
        if repo_data['name'].lower() != repo_name.lower():
            continue
        for v in repo_data['versions']:
            if f"{v['version']}-{v['build']}" == ver_str:
                from .pkgman import Version

                selected = AvailableVersion(
                    version=Version(v['build'], v['version']),
                    url=v['url'],
                    is_prerelease=v.get('is_prerelease', False),
                )
                repo_config = RepoConfig.find_by_name(repo_data['name'])
                try:
                    CamoufoxUpdate(repo_config=repo_config, selected_version=selected).update()
                except Exception as e:
                    msg = str(e)
                    if '404' in msg or 'Not Found' in msg:
                        rprint("Release not found (404). Asset may have been removed.", fg="red")
                        rprint("Run 'camoufox sync' to refresh available versions.", fg="yellow")
                    else:
                        rprint(f"Error: {msg}", fg="red")
                    return
                if ALLOW_GEOIP:
                    download_mmdb()
                maybe_download_addons(list(DefaultAddons))
                return

    rprint(f"Version '{version or ver_str}' not found in cache.", fg="red")


def _set_channel(repo_name: str, channel_type: str):
    """
    Set to track a channel (fetches latest on fetch)
    """
    config = load_config()
    config['channel'] = f"{repo_name}/{channel_type}"
    config.pop('pinned', None)
    save_config(config)
    click.secho(f"Channel: {repo_name.lower()}/{channel_type}", fg="cyan", bold=True)

    # Check if latest for this channel is already installed
    is_pre = channel_type == "prerelease"
    cache = load_repo_cache()
    for repo_data in cache.get('repos', []):
        if repo_data['name'].lower() != repo_name.lower():
            continue
        versions = repo_data.get('versions', [])
        candidates = [v for v in versions if v.get('is_prerelease', False) == is_pre]
        if candidates:
            latest_build = candidates[0]['build']
            for inst in list_installed():
                if inst.version.build == latest_build and inst.repo_name == repo_name.lower():
                    set_active(inst.relative_path)
                    click.secho(f"Using latest: {inst.channel_path} (installed)", fg="green")
                    return
        break

    click.secho("Run 'camoufox fetch' to install latest.", fg="yellow")


def _set_pinned(repo_name: str, channel_type: str, ver_data: dict, inst):
    """
    Pin to a specific version
    """
    config = load_config()
    config['channel'] = f"{repo_name}/{channel_type}"
    config['pinned'] = f"{ver_data['version']}-{ver_data['build']}"
    save_config(config)
    ver_str = f"{ver_data['version']}-{ver_data['build']}"
    display = f"{repo_name.lower()}/{channel_type}/{ver_str}"
    if inst:
        set_active(inst.relative_path)
        click.secho(f"Pinned: {display} (installed)", fg="green")
    else:
        click.secho(f"Pinned: {display}", fg="cyan", bold=True)
        click.secho("Run 'camoufox fetch' to install.", fg="yellow")


@cli.command(name='set')
@click.argument('specifier', required=False)
@click.option('--geoip', is_flag=True, help='Select GeoIP source instead')
def set_cmd(specifier, geoip):
    """
    \b
    Interactive selector for versions and settings
    Or, pass a specifier to activate directly:
        Pin version:          camoufox set official/stable/134.0.2-beta.20
        Auto-update channel:  camoufox set official/stable
    """
    if geoip:
        _select_geoip_source()
        return

    if specifier:
        parts = specifier.lower().split('/')

        # 2-part: set channel (e.g. official/stable)
        if len(parts) == 2:
            repo_name, ctype = parts
            if ctype not in ('stable', 'prerelease'):
                rprint(f"Unknown channel type '{ctype}'. Use 'stable' or 'prerelease'.", fg="red")
                return
            _set_channel(repo_name, ctype)
            return

        # 3-part: pin version (e.g. official/stable/146.0.1-beta.25)
        if len(parts) == 3:
            repo_name, ctype, ver_str = parts
            if ctype not in ('stable', 'prerelease'):
                rprint(f"Unknown channel type '{ctype}'. Use 'stable' or 'prerelease'.", fg="red")
                return
            # Activate if already installed
            target = _find_installed(specifier)
            if target:
                set_active(target.relative_path)
                rprint(f"Pinned: {target.channel_path} (installed)", fg="green")
            else:
                click.secho(f"Pinned: {repo_name}/{ctype}/{ver_str}", fg="cyan", bold=True)
                rprint("Run 'camoufox fetch' to install.", fg="yellow")
            # Save pin config either way
            config = load_config()
            config['channel'] = f"{repo_name}/{ctype}"
            config['pinned'] = ver_str
            save_config(config)
            return

        rprint(f"Invalid specifier '{specifier}'.", fg="red")
        rprint("Use: repo/channel or repo/channel/version", fg="yellow")
        return

    if not _ensure_synced():
        return

    import inquirer
    from inquirer.themes import GreenPassion

    cache = load_repo_cache()
    installed = {v.version.build: v for v in list_installed()}

    if not cache.get('repos'):
        rprint("No versions in cache. Run 'camoufox sync' first.", fg="red")
        return

    channels = []
    for repo_data in cache['repos']:
        name = repo_data['name']
        versions = repo_data.get('versions', [])
        stable = [v for v in versions if not v.get('is_prerelease')]
        prereleases = [v for v in versions if v.get('is_prerelease')]
        if stable:
            channels.append((name, 'stable', stable[0]))
        if prereleases:
            channels.append((name, 'prerelease', prereleases[0]))

    config = load_config()
    channel = config.get('channel') or get_default_channel()
    pinned = config.get('pinned')

    if pinned:
        click.secho(f"Pinned: {channel.lower()}/{pinned}", fg="cyan")
    else:
        click.secho(f"Channel: {channel.lower()}", fg="cyan")
    click.echo()

    channel_versions = {}
    for repo_data in cache['repos']:
        name = repo_data['name']
        versions = repo_data.get('versions', [])
        stable = [v for v in versions if not v.get('is_prerelease')]
        prereleases = [v for v in versions if v.get('is_prerelease')]
        if stable:
            channel_versions[(name, 'stable')] = stable
        if prereleases:
            channel_versions[(name, 'prerelease')] = prereleases

    while True:
        choices = [("Set channel", 'channel')]
        for (name, ctype), versions in channel_versions.items():
            label = f"Pin version: {click.style(f'{name.lower()}/{ctype}', fg='cyan', bold=True)}"
            choices.append((label, ('pin', name, ctype, versions)))
        choices.append((click.style("Exit", fg="bright_black"), 'exit'))

        answer = inquirer.prompt(
            [inquirer.List('action', message="Select", choices=choices, carousel=True)],
            theme=GreenPassion(),
        )
        if not answer:
            return

        action = answer['action']

        if action == 'exit':
            return

        elif action == 'channel':
            ch_choices = []
            for name, ctype, latest in channels:
                ver_str = f"v{latest['version']}-{latest['build']}"
                is_current = channel == f"{name}/{ctype}"
                label = f"{name.lower()}/{ctype} (latest: {ver_str})"
                if is_current:
                    label = click.style(label, fg="green", bold=True) + " (current)"
                ch_choices.append((label, (name, ctype, latest)))
            ch_choices.append((click.style("Back", fg="bright_black"), None))

            ch_answer = inquirer.prompt(
                [
                    inquirer.List(
                        'channel', message="Set channel", choices=ch_choices, carousel=True
                    )
                ],
                theme=GreenPassion(),
            )
            if not ch_answer or ch_answer['channel'] is None:
                continue

            repo_name, ctype, _ = ch_answer['channel']
            _set_channel(repo_name, ctype)
            return

        elif isinstance(action, tuple) and action[0] == 'pin':
            _, rname, ctype, versions = action

            v_choices = []
            for i, v in enumerate(versions):
                build = v['build']
                full_ver = f"{v['version']}-{build}"
                inst = installed.get(build)
                is_last = i == len(versions) - 1

                prefix = "└── " if is_last else "├── "

                is_pinned = pinned == full_ver
                if is_pinned and inst:
                    color = "green"
                    bold = True
                    suffix = " (pinned)"
                elif is_pinned:
                    color = "cyan"
                    bold = True
                    suffix = " (pinned, not installed)"
                elif inst:
                    color = None  # white
                    bold = False
                    suffix = " (installed)"
                else:
                    color = "bright_black"  # grayed out
                    bold = False
                    suffix = ""

                ver_str = click.style(f"v{full_ver}", fg=color, bold=bold)
                v_choices.append((f"{prefix}{ver_str}{suffix}", v))

            v_choices.append((click.style("Back", fg="bright_black"), None))

            default_val = versions[0] if versions else None
            v_answer = inquirer.prompt(
                [
                    inquirer.List(
                        'version',
                        message=f"Pin version ({rname.lower()}/{ctype})",
                        choices=v_choices,
                        default=default_val,
                    )
                ],
                theme=GreenPassion(),
            )
            if not v_answer or v_answer['version'] is None:
                continue

            ver_data = v_answer['version']
            inst = installed.get(ver_data['build'])
            _set_pinned(rname, ctype, ver_data, inst)
            return


def _select_geoip_source():
    """
    Interactive selection of GeoIP source
    """
    repos, _ = _load_geoip_repos()
    if not repos:
        rprint("No GeoIP sources configured.", fg="red")
        return

    current = load_geoip_config().get('name', '')
    choices = [(r['name'] + (" [active]" if r.get('name') == current else ""), r) for r in repos]

    selected = _inquirer_select(choices, "Select GeoIP source")
    if not selected:
        return

    save_geoip_config(selected)
    rprint(f"GeoIP source: {selected['name']}", fg="green")


@cli.command(name='list')
@click.argument('mode', default='installed', type=click.Choice(['installed', 'all']))
@click.option('--path', 'show_paths', is_flag=True, help='Show full paths')
def list_cmd(mode, show_paths):
    """
    List Camoufox versions.

    \b
    MODES:
      installed  Show installed versions (default)
      all        Show all available versions from synced repos
    """
    if mode == 'all':
        _list_all(show_paths)
    else:
        _list_installed(show_paths)


def _list_installed(show_paths: bool):
    """
    List installed versions
    """
    print_tree(show_paths=show_paths)

    click.echo()
    click.secho("geoip/", fg="cyan", bold=True, nl=False)
    if show_paths and GEOIP_DIR.exists():
        click.secho(f" -> {GEOIP_DIR}", fg="bright_black")
    else:
        click.echo()

    if GEOIP_DIR.exists():
        mmdb = get_mmdb_path()
        if mmdb.exists():
            click.echo(f"    └── {mmdb.name} ", nl=False)
            click.secho(f"({_get_geoip_source_name()})", fg="green")
        else:
            rprint("    └── Not downloaded", fg="yellow")
    else:
        rprint("    └── Not configured", fg="yellow")


def _list_all(_show_paths: bool):
    """
    List all available versions from synced repos
    """
    if not _ensure_synced():
        return

    cache = load_repo_cache()
    installed = {v.version.build: v for v in list_installed()}

    rprint("Available versions:\n", fg="yellow")

    for repo_data in cache.get('repos', []):
        rname = repo_data['name']
        versions = repo_data.get('versions', [])

        click.secho(f"{rname}/", fg="cyan", bold=True)

        for i, v in enumerate(versions):
            build = v['build']
            full_ver = f"{v['version']}-{build}"
            inst = installed.get(build)
            is_last = i == len(versions) - 1

            prefix = "└── " if is_last else "├── "
            color = "green" if inst and inst.is_active else None

            click.echo(f"    {prefix}", nl=False)
            click.secho(f"v{full_ver}", fg=color, bold=inst and inst.is_active, nl=False)

            if v.get('is_prerelease'):
                click.secho(" (prerelease)", fg="yellow", nl=False)
            else:
                click.secho(" (stable)", fg="blue", nl=False)

            if inst:
                if inst.is_active:
                    click.secho(" (installed, active)", fg="green", bold=True, nl=False)
                else:
                    click.secho(" (installed)", fg="green", nl=False)

            click.echo()

        click.echo()


@cli.command(name='remove')
@click.argument('version_path', required=False)
@click.option('--all', 'remove_all', is_flag=True, help='Remove everything')
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompts')
def remove(version_path, remove_all, yes):
    """
    \b
    Remove installed version(s)
    Or, pass a specifier to remove directly:
      camoufox remove official/stable/134.0.2-beta.20
    """
    installed = list_installed()
    has_geoip = GEOIP_DIR.exists()

    if remove_all or version_path == 'all':
        has_config = CONFIG_FILE.exists() or REPO_CACHE_FILE.exists()
        if not installed and not has_geoip and not has_config:
            rprint("Nothing to remove.", fg="yellow")
            return
        if installed and (yes or click.confirm(f"Remove all {len(installed)} browser version(s)?")):
            for v in installed:
                remove_version(v.path)
            rprint(f"Removed {len(installed)} version(s).", fg="green")
        if has_geoip and (yes or click.confirm("Remove GeoIP database?")):
            remove_mmdb()
        # Clean up config files
        for f in (CONFIG_FILE, REPO_CACHE_FILE):
            if f.exists():
                f.unlink()
        # Remove install dir if empty
        if INSTALL_DIR.exists() and not any(INSTALL_DIR.iterdir()):
            INSTALL_DIR.rmdir()
        return

    if not installed:
        rprint("No browser versions installed.", fg="yellow")
        if has_geoip and (yes or click.confirm("Remove GeoIP database?")):
            remove_mmdb()
        return

    if version_path:
        target = _find_installed(version_path)
        if not target:
            rprint(f"Version '{version_path}' not found.", fg="red")
            return
    else:
        choices = [
            (v.channel_path + (" [active]" if v.is_active else ""), v)
            for v in installed
        ]
        target = _inquirer_select(choices, "Select version to remove")
        if not target:
            rprint("Cancelled.", fg="yellow")
            return

    if yes or click.confirm(f"Remove {target.channel_path}?"):
        remove_version(target.path)
        rprint(f"Removed {target.channel_path}", fg="green")

    if has_geoip and (yes or click.confirm("Also remove GeoIP?", default=False)):
        remove_mmdb()


@cli.command(name='test')
@click.option('--executable-path', help='Path to the Camoufox executable', default=None)
@click.argument('url', default=None, required=False)
def test(url: Optional[str] = None, executable_path: Optional[str] = None) -> None:
    """
    Open the Playwright inspector
    """
    from .sync_api import Camoufox

    with Camoufox(headless=False, env=environ, config={'showcursor': False}, executable_path=executable_path) as browser:
        page = browser.new_page()
        if url:
            page.goto(url)
        page.pause()


@cli.command(name='server')
def server():
    """
    Launch a Playwright server
    """
    from .server import launch_server

    launch_server()


@cli.command(name='gui')
@click.option('--debug', is_flag=True, help="Enable debug options in the GUI.")
def gui(debug):
    """
    Launch the Camouman GUI (requires PySide6)
    """
    try:
        from .gui import main

        main(debug=debug)
    except ImportError:
        rprint("GUI requires PySide6. Install with: pip install 'camoufox\\[gui]'", fg="red")


class VersionInfo:
    def __init__(self):
        from rich.table import Table
        from rich.text import Text

        from .pkgman import console

        self.Text = Text
        self.console = console
        self.t = Table.grid(padding=(0, 2))

    def _row(self, label, value, style="green"):
        """
        Print a row to the table
        """
        self.t.add_row(self.Text(f"  {label}", style="dim"), self.Text(value, style=style))

    def _header(self, title):
        """
        Print a section title to the table
        """
        self.t.add_row(self.Text(title, style="bold"), self.Text(""))

    def _pkg(self, label, pkg_name):
        try:
            self._row(label, f"v{pkg_version(pkg_name)}")
        except PackageNotFoundError:
            self._row(label, "?", style="dim")

    def packages(self):
        """
        Gets installed package versions
        """
        self._header("Python Packages")
        self._pkg("Camoufox", "camoufox")
        self._pkg("Browserforge", "browserforge")
        self._pkg("Apify Fingerprints", "apify_fingerprint_datapoints")
        self._pkg("Playwright", "playwright")

    def browser(self):
        """
        Gets active browser, installed version, and sync status
        """
        from datetime import datetime, timezone

        self._header("Browser")

        config = load_config()
        pinned = config.get('pinned')
        channel = config.get('channel') or get_default_channel()

        # Active: what was set (channel or pinned version)
        if pinned:
            self._row("Active", f"{channel.lower()}/{pinned}")
        else:
            self._row("Active", channel.lower())

        # Find the active installed version
        active_v = None
        for v in list_installed():
            if v.is_active:
                active_v = v
                break

        # Browser version
        if active_v:
            self._row("Browser", f"v{active_v.version.full_string}")
        else:
            self._row("Browser", "—", style="dim")

        # Is installed?
        if active_v:
            self._row("Installed", "Yes", style="green")
        else:
            self._row("Installed", "No", style="red")

        # Check if installed version is the latest in its own channel
        if active_v:
            ctype = "prerelease" if active_v.is_prerelease else "stable"
            repo_ch = f"{active_v.repo_name}/{ctype}"
            is_latest = False
            cache = load_repo_cache()
            for repo_data in cache.get('repos', []):
                if repo_data['name'].lower() != active_v.repo_name.lower():
                    continue
                candidates = [v for v in repo_data.get('versions', []) if v.get('is_prerelease', False) == active_v.is_prerelease]
                if candidates and active_v.version.build == candidates[0]['build']:
                    is_latest = True
                break
            self._row(
                f"Latest in {repo_ch}?",
                "Yes" if is_latest else "No",
                style="green" if is_latest else "red",
            )

        # Last repo sync time from cache file mtime
        if REPO_CACHE_FILE.exists():
            mtime = REPO_CACHE_FILE.stat().st_mtime
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone()
            self._row("Last Sync", dt.strftime('%Y-%m-%d %H:%M'), style="dim")
        else:
            self._row("Last Sync", "Never", style="red")

    def geoip(self):
        """
        Get info about the geoip db and check if its there
        """
        from datetime import datetime, timezone

        self._header("GeoIP")
        if not ALLOW_GEOIP:
            # geoip2 package not installed
            self._row("Status", "Not supported (install camoufox[geoip])", style="dim")
        else:
            mmdb_path = get_mmdb_path()
            if mmdb_path.exists():
                # Show active database name and last update time
                geoip_cfg = load_geoip_config()
                self._row("Database", geoip_cfg.get('name', 'Unknown'))
                mtime = mmdb_path.stat().st_mtime
                dt = datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone()
                self._row("Updated", dt.strftime('%Y-%m-%d %H:%M'), style="dim")
            else:
                self._row("Database", "Not installed", style="dim")

    def _dir_size(self, path) -> str:
        if not path.exists():
            return "—"
        total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        for unit in ('B', 'KB', 'MB'):
            if total < 1024:
                return f"{total:.1f} {unit}" if unit != 'B' else f"{total} B"
            total /= 1024
        return f"{total:.1f} GB"

    def storage(self):
        """
        Get paths and directory sizes
        """
        self._header("Storage")
        self._row("Install path", str(INSTALL_DIR), style="cyan")
        self._row("Browser(s) directory size", self._dir_size(BROWSERS_DIR), style="dim")
        if ALLOW_GEOIP:
            self._row("GeoIP database size", self._dir_size(GEOIP_DIR), style="dim")
        self._row("Config file", str(CONFIG_FILE), style="cyan")
        self._row("Repo cache", str(REPO_CACHE_FILE), style="cyan")

    def print_all(self):
        self.packages()
        self.browser()
        self.geoip()
        self.storage()
        self.console.print(self.t)


@cli.command(name='version')
def version():
    """
    Display version, package, browser, and storage info
    """
    VersionInfo().print_all()


@cli.command(name='active')
def active_cmd():
    """
    Print the current active version
    """
    installed = list_installed()
    for v in installed:
        if v.is_active:
            click.echo(v.channel_path)
            return

    config = load_config()
    pinned = config.get('pinned')
    channel = config.get('channel') or get_default_channel()
    if pinned:
        click.echo(f"{channel.lower()}/{pinned} ", nl=False)
        rprint("(not installed)", fg="yellow")
    else:
        click.echo(f"{channel.lower()} ", nl=False)
        rprint("(not installed)", fg="yellow")


@cli.command(name='path')
def path_cmd():
    """
    Print the install directory path
    """
    click.echo(INSTALL_DIR)


if __name__ == '__main__':
    cli()
