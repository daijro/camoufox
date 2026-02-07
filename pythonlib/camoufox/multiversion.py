"""
Manager for handling multiple Camoufox versions side by side
"""

import os
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .pkgman import AvailableVersion

import orjson
import rich_click as click

from .pkgman import INSTALL_DIR, OS_NAME, Version, rprint, unzip

BROWSERS_DIR: Path = INSTALL_DIR / "browsers"
CONFIG_FILE: Path = INSTALL_DIR / "config.json"
REPO_CACHE_FILE: Path = INSTALL_DIR / "repo_cache.json"


def load_config() -> Dict:
    """
    Load user config from disk, or return empty dict
    """
    if CONFIG_FILE.exists():
        try:
            return orjson.loads(CONFIG_FILE.read_bytes())
        except orjson.JSONDecodeError:
            pass
    return {}


def save_config(config: Dict) -> None:
    """
    Save user config to disk
    """
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_bytes(orjson.dumps(config, option=orjson.OPT_INDENT_2))


def load_repo_cache() -> Dict:
    """
    Load cached repo data from disk
    """
    if REPO_CACHE_FILE.exists():
        try:
            return orjson.loads(REPO_CACHE_FILE.read_bytes())
        except orjson.JSONDecodeError:
            pass
    return {}


def save_repo_cache(cache: Dict) -> None:
    """
    Save repo cache to disk
    """
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    REPO_CACHE_FILE.write_bytes(orjson.dumps(cache, option=orjson.OPT_INDENT_2))


def get_cached_versions(repo_name: Optional[str] = None) -> List['AvailableVersion']:
    """
    Get cached available versions, optionally filtered by repo
    """
    from .pkgman import AvailableVersion, Version

    cache = load_repo_cache()
    if not cache.get('repos'):
        return []

    versions = []
    for repo_data in cache['repos']:
        if repo_name and repo_data['name'].lower() != repo_name.lower():
            continue
        for v in repo_data.get('versions', []):
            versions.append(
                AvailableVersion(
                    version=Version(build=v['build'], version=v['version']),
                    url=v['url'],
                    is_prerelease=v.get('is_prerelease', False),
                    asset_id=v.get('asset_id'),
                    asset_size=v.get('asset_size'),
                    asset_updated_at=v.get('asset_updated_at'),
                )
            )

    versions.sort(key=lambda x: x.version, reverse=True)
    return versions


def get_cached_repo_names() -> List[str]:
    """
    Get list of repo names in cache
    """
    cache = load_repo_cache()
    return [r['name'] for r in cache.get('repos', [])]


def get_repo_name(github_repo: str) -> str:
    """
    Get display name for a repo from repos.yml, lowercased
    """
    from .pkgman import RepoConfig

    for repo in RepoConfig.load_repos():
        if repo.repo == github_repo:
            return repo.name.lower()
    return github_repo.split('/')[0].lower()


@dataclass
class InstalledVersion:
    """
    Information about an installed Camoufox version
    """

    repo_name: str
    version: Version
    path: Path
    is_active: bool = False
    is_prerelease: bool = False
    asset_id: Optional[int] = None
    asset_size: Optional[int] = None
    asset_updated_at: Optional[str] = None

    @property
    def relative_path(self) -> str:
        """
        Path relative to INSTALL_DIR (like browsers/official/134.0.2-beta.20)
        """
        return f"browsers/{self.repo_name}/{self.version.full_string}"

    @property
    def channel_path(self) -> str:
        """
        Channel display string (like official/stable/134.0.2-beta.20)
        """
        ctype = "prerelease" if self.is_prerelease else "stable"
        return f"{self.repo_name}/{ctype}/{self.version.full_string}"

    def get_changes(self, available: 'AvailableVersion') -> List[str]:
        """
        Compare with an available version and return change indicators
        """
        changes: List[str] = []
        if self.is_prerelease and not available.is_prerelease:
            changes.append("prerelease -> stable")
        elif not self.is_prerelease and available.is_prerelease:
            changes.append("stable -> prerelease")

        if self.asset_updated_at and available.asset_updated_at:
            if self.asset_updated_at != available.asset_updated_at:
                changes.append("asset updated")
        elif self.asset_size and available.asset_size:
            if self.asset_size != available.asset_size:
                changes.append("asset updated")

        return changes


def find_installed_by_build(
    build: str, repo_name: Optional[str] = None
) -> Optional[InstalledVersion]:
    """
    Find an installed version by its build string
    """
    for v in list_installed():
        if v.version.build == build:
            if repo_name is None or v.repo_name == repo_name:
                return v
    return None


def list_installed() -> List[InstalledVersion]:
    """
    Scan browsers/ for installed versions, sorted by repo then version descending
    """
    installed: List[InstalledVersion] = []
    config = load_config()
    active = config.get('active_version')

    if not BROWSERS_DIR.exists():
        return installed

    for repo_dir in BROWSERS_DIR.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith('.'):
            continue

        for version_dir in repo_dir.iterdir():
            if not version_dir.is_dir():
                continue

            version_json = version_dir / 'version.json'
            if not version_json.exists():
                continue

            try:
                ver = Version.from_path(version_dir)
                with open(version_json, 'rb') as f:
                    version_data = orjson.loads(f.read())
                rel_path = f"browsers/{repo_dir.name}/{ver.full_string}"
                installed.append(
                    InstalledVersion(
                        repo_name=repo_dir.name,
                        version=ver,
                        path=version_dir,
                        is_active=(rel_path == active),
                        is_prerelease=version_data.get('prerelease', False),
                        asset_id=version_data.get('asset_id'),
                        asset_size=version_data.get('asset_size'),
                        asset_updated_at=version_data.get('asset_updated_at'),
                    )
                )
            except (FileNotFoundError, orjson.JSONDecodeError):
                continue

    installed.sort(key=lambda x: (x.repo_name, x.version), reverse=True)
    return installed


def get_active_path() -> Optional[Path]:
    """
    Get path to active version. Auto-selects newest if none set
    """
    config = load_config()
    active = config.get('active_version')

    if active:
        path = INSTALL_DIR / active
        if path.exists() and (path / 'version.json').exists():
            return path

    installed = list_installed()
    if installed:
        config['active_version'] = installed[0].relative_path
        save_config(config)
        return installed[0].path

    return None


def set_active(relative_path: str) -> None:
    """
    Set the active version by its relative path
    """
    config = load_config()
    config['active_version'] = relative_path
    save_config(config)


def find_installed_version(specifier: str) -> Optional[Path]:
    """
    Find an installed version by path, build, full version, or repo/build
    """
    installed = list_installed()
    if not installed:
        return None

    specifier_lower = specifier.lower()

    for v in installed:
        if v.relative_path == specifier or v.relative_path == f"browsers/{specifier}":
            return v.path
        if f"browsers/{v.repo_name}/{v.version.full_string}".endswith(specifier):
            return v.path
        if f"{v.repo_name}/{v.version.build}".lower() == specifier_lower:
            return v.path
        if v.version.build.lower() == specifier_lower:
            return v.path
        if v.version.full_string.lower() == specifier_lower:
            return v.path
        if v.version.version and v.version.version.lower() == specifier_lower:
            return v.path

    return None


def install_versioned(fetcher, replace: bool = False) -> bool:
    """
    Install to browsers/{repo_name}/{version}-{build}/
    """
    repo_name = get_repo_name(fetcher.github_repo)
    version_folder = f"{fetcher.version}-{fetcher.build}"
    install_path = BROWSERS_DIR / repo_name / version_folder

    if install_path.exists() and (install_path / 'version.json').exists():
        if not replace:
            installed_v = find_installed_by_build(fetcher.build, repo_name)
            change_msg = ""
            if installed_v and fetcher._selected_version:
                changes = installed_v.get_changes(fetcher._selected_version)
                if changes:
                    change_msg = f" ({', '.join(changes)})"

            rprint(f"Version v{fetcher.verstr} already installed{change_msg}.", fg="yellow")
            if change_msg:
                rprint("Use --replace to update with the new release.", fg="yellow")
            else:
                rprint("Use --replace to reinstall.", fg="yellow")
            if not load_config().get('active_version'):
                set_active(f"browsers/{repo_name}/{version_folder}")
            return False
        rprint(f"Replacing: {install_path}", fg="yellow")
        shutil.rmtree(install_path)

    try:
        install_path.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile() as temp_file:
            fetcher.download_file(temp_file, fetcher.url)
            rprint(f'Extracting Camoufox: {install_path}')
            unzip(temp_file, str(install_path))

            if fetcher._selected_version:
                metadata = fetcher._selected_version.to_metadata()
            else:
                metadata = {
                    'version': fetcher.version,
                    'build': fetcher.build,
                    'prerelease': fetcher.is_prerelease,
                }
            with open(install_path / 'version.json', 'wb') as f:
                f.write(orjson.dumps(metadata))

        if OS_NAME != 'win':
            os.system(f'chmod -R 755 {shlex.quote(str(install_path))}')  # nosec

        set_active(f"browsers/{repo_name}/{version_folder}")

        rprint(f'\nCamoufox v{fetcher.verstr} installed.', fg="green")
        rprint(f'Path: {install_path}', fg="green")
        return True

    except Exception as e:
        rprint(f"Error: {e}", fg="red")
        if install_path.exists():
            shutil.rmtree(install_path)
        raise


def remove_version(path: Path) -> bool:
    """
    Remove a specific version installation
    """
    if not path.exists():
        return False

    rprint(f'Removing: {path}')
    shutil.rmtree(path)

    parent = path.parent
    if parent.exists() and parent != BROWSERS_DIR and not any(parent.iterdir()):
        parent.rmdir()
    if BROWSERS_DIR.exists() and not any(BROWSERS_DIR.iterdir()):
        BROWSERS_DIR.rmdir()

    config = load_config()
    try:
        rel_path = str(path.relative_to(INSTALL_DIR))
        if config.get('active_version') == rel_path:
            remaining = list_installed()
            config['active_version'] = remaining[0].relative_path if remaining else None
            save_config(config)
    except ValueError:
        pass  # Path not relative to INSTALL_DIR

    return True


def print_tree(show_header: bool = True, show_paths: bool = False) -> None:
    """
    Print installed versions as a tree
    """
    installed = list_installed()

    if not installed:
        rprint("No versions installed.", fg="yellow")
        rprint("Run `camoufox fetch` to install.", fg="yellow")
        return

    if show_header:
        rprint("Installed versions:\n", fg="yellow")

    current_repo = None
    for i, v in enumerate(installed):
        is_last = (i == len(installed) - 1) or (installed[i + 1].repo_name != v.repo_name)

        if v.repo_name != current_repo:
            current_repo = v.repo_name
            click.secho(f"{current_repo}/", fg="cyan", bold=True, nl=False)
            if show_paths:
                click.secho(f" -> {BROWSERS_DIR / current_repo}", fg="bright_black")
            else:
                click.echo()

        branch = "└── " if is_last else "├── "
        color = "green" if v.is_active else None

        click.echo(f"    {branch}", nl=False)
        click.secho(f"v{v.version.full_string}", fg=color, bold=v.is_active, nl=False)
        if v.is_prerelease:
            click.secho(" (prerelease)", fg="yellow", nl=False)
        else:
            click.secho(" (stable)", fg="blue", nl=False)
        if v.is_active:
            click.secho(" (active)", fg="green", bold=True, nl=False)
        click.echo()
