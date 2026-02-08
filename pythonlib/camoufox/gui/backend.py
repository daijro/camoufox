import os
import sys
import tempfile
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..multiversion import (
    BROWSERS_DIR,
    get_cached_versions,
    get_default_channel,
    get_repo_name,
    list_installed,
    load_config,
    load_repo_cache,
    remove_version,
    save_config,
    save_repo_cache,
    set_active,
)
from ..pkgman import RepoConfig, unzip, webdl

# Workers

class Worker(QThread):
    progress = Signal(float)
    status = Signal(str)
    done = Signal(bool, str)

    def _progress(self, downloaded, total):
        if total > 0:
            self.progress.emit(downloaded / total)


class DownloadWorker(Worker):
    def __init__(self, repo_config, version):
        super().__init__()
        self.repo_config = repo_config
        self.version = version

    def run(self):
        try:
            import shlex

            import orjson

            self.status.emit("Downloading...")
            repo_name = get_repo_name(self.repo_config.repo)
            folder = f"{self.version.version.version}-{self.version.version.build}"
            path = BROWSERS_DIR / repo_name / folder
            path.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile() as f:
                webdl(self.version.url, buffer=f, bar=False, progress_callback=self._progress)
                self.status.emit("Extracting...")
                self.progress.emit(-1)
                unzip(f, str(path), bar=False)

            (path / 'version.json').write_bytes(orjson.dumps(self.version.to_metadata()))

            if sys.platform != 'win32':
                os.system(f'chmod -R 755 {shlex.quote(str(path))}')

            set_active(f"browsers/{repo_name}/{folder}")
            self.done.emit(True, f"Installed v{self.version.version.full_string}")
        except Exception as e:
            msg = str(e)
            if '404' in msg or 'Not Found' in msg:
                self.done.emit(False, "Release not found (404). Please resync.")
            else:
                self.done.emit(False, msg)


class SyncWorker(Worker):
    def __init__(self, spoof_os=None, spoof_arch=None, spoof_lib_ver=None):
        super().__init__()
        self.spoof_os = spoof_os
        self.spoof_arch = spoof_arch
        self.spoof_lib_ver = spoof_lib_ver

    def run(self):
        try:
            from datetime import datetime

            from ..pkgman import list_available_versions

            self.status.emit("Syncing...")
            cache = {'repos': []}

            for rc in RepoConfig.load_repos(spoof_library_version=self.spoof_lib_ver):
                self.status.emit(f"Syncing {rc.name}...")
                versions = list_available_versions(
                    rc,
                    include_prerelease=True,
                    spoof_os=self.spoof_os,
                    spoof_arch=self.spoof_arch,
                )
                cache['repos'].append({
                    'name': rc.name,
                    'repo': rc.repo,
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
                })

            cache['spoof_os'] = self.spoof_os
            cache['spoof_arch'] = self.spoof_arch
            cache['spoof_lib_ver'] = self.spoof_lib_ver
            _dfmt = '%#m/%#d/%Y %#I:%M %p' if sys.platform == 'win32' else '%-m/%-d/%Y %-I:%M %p'
            cache['sync_time'] = datetime.now().strftime(_dfmt)
            save_repo_cache(cache)
            total = sum(len(r['versions']) for r in cache['repos'])
            self.done.emit(True, f"Synced {total} versions")
        except Exception as e:
            self.done.emit(False, str(e))


class GeoIPWorker(Worker):
    def __init__(self, source):
        super().__init__()
        self.source = source

    def run(self):
        try:
            from ..geolocation import download_mmdb

            download_mmdb(source=self.source, progress_callback=self._progress)
            self.done.emit(True, f"Installed: {self.source}")
        except Exception as e:
            self.done.emit(False, str(e))


# Models

class Roles(IntEnum):
    Display = Qt.ItemDataRole.UserRole + 1
    Build = Qt.ItemDataRole.UserRole + 2
    IsHeader = Qt.ItemDataRole.UserRole + 3
    IsPrerelease = Qt.ItemDataRole.UserRole + 4
    IsActive = Qt.ItemDataRole.UserRole + 5
    IsInstalled = Qt.ItemDataRole.UserRole + 6
    Section = Qt.ItemDataRole.UserRole + 7
    Expanded = Qt.ItemDataRole.UserRole + 8
    IsPinned = Qt.ItemDataRole.UserRole + 9


_ROLE_ATTRS = {
    Roles.Display: 'display', Roles.Build: 'build',
    Roles.IsHeader: 'is_header', Roles.IsPrerelease: 'is_prerelease',
    Roles.IsActive: 'is_active', Roles.IsInstalled: 'is_installed',
    Roles.Section: 'section', Roles.Expanded: 'expanded',
    Roles.IsPinned: 'is_pinned',
}

_BOOL_ROLES = {
    Roles.IsHeader, Roles.IsPrerelease, Roles.IsActive,
    Roles.IsInstalled, Roles.Expanded, Roles.IsPinned,
}

_ROLE_NAMES = {
    Roles.Display: b"display", Roles.Build: b"build",
    Roles.IsHeader: b"isHeader", Roles.IsPrerelease: b"isPrerelease",
    Roles.IsActive: b"isActive", Roles.IsInstalled: b"isInstalled",
    Roles.Section: b"section", Roles.Expanded: b"expanded",
    Roles.IsPinned: b"isPinned",
}


class VersionItem:
    __slots__ = (
        'display', 'build', 'is_header', 'is_prerelease', 'is_active',
        'is_pinned', 'is_installed', 'section', 'expanded',
        'version_data', 'installed_data',
    )

    def __init__(
        self, display, build="", is_header=False, is_prerelease=False,
        is_active=False, is_pinned=False, is_installed=False,
        section="", expanded=True, version_data=None, installed_data=None,
    ):
        self.display = display
        self.build = build
        self.is_header = is_header
        self.is_prerelease = is_prerelease
        self.is_active = is_active
        self.is_pinned = is_pinned
        self.is_installed = is_installed
        self.section = section
        self.expanded = expanded
        self.version_data = version_data
        self.installed_data = installed_data


class VersionModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []

    def rowCount(self, parent=QModelIndex()):
        return len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return False if role in _BOOL_ROLES else ""
        attr = _ROLE_ATTRS.get(role)
        return getattr(self._items[index.row()], attr, "") if attr else ""

    def roleNames(self):
        return _ROLE_NAMES

    def set_items(self, items):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def get(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None


OS_OPTIONS = ["(auto)", "mac", "win", "lin"]
ARCH_OPTIONS = ["(auto)", "x86_64", "i686", "arm64"]


# Backend

class Backend(QObject):
    reposChanged = Signal()
    busyChanged = Signal()
    progressChanged = Signal()
    statusChanged = Signal()
    selectionChanged = Signal()
    geoipChanged = Signal()
    infoChanged = Signal()
    debugChanged = Signal()
    currentRepoChanged = Signal()
    channelPrompt = Signal(int, str, str)

    def __init__(self):
        super().__init__()
        self._repo_configs = list(RepoConfig.load_repos())
        self._repos = [r.name for r in self._repo_configs]
        self._version_model = VersionModel(self)
        self._current_repo = self._repo_configs[0] if self._repo_configs else None

        self._selected = -1
        self._busy = False
        self._progress = -1.0
        self._status_text = ""
        self._status_color = "#888"
        self._installed_only = False
        self._sections = {"stable": True, "prerelease": True}
        self._worker = None
        self._channel_data = None

        self._geoip_available = False
        self._geoip_sources = []
        self._geoip_names = []
        self._geoip_installed = ""
        self._geoip_downloaded = []
        self._geoip_path = ""
        self._geoip_size = ""
        self._geoip_mtime = ""
        self._geoip_busy = False
        self._geoip_progress = -1.0
        self._lookup_result = ""
        self._lookup_ok = True

        self._spoof_os_idx = 0
        self._spoof_arch_idx = 0
        self._spoof_lib_ver = ""
        self._pending_channel = None
        self._load_spoof_from_cache()
        self._load_geoip()

    # Properties

    @Property(list, notify=reposChanged)
    def repos(self):
        return self._repos

    @Property(QObject, constant=True)
    def versionModel(self):
        return self._version_model

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(float, notify=progressChanged)
    def progress(self):
        return self._progress

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    @Property(str, notify=statusChanged)
    def statusColor(self):
        return self._status_color

    @Property(bool, notify=selectionChanged)
    def canInstall(self):
        item = self._version_model.get(self._selected)
        return item and not item.is_header and not item.is_installed

    @Property(bool, notify=selectionChanged)
    def canUninstall(self):
        item = self._version_model.get(self._selected)
        return item and not item.is_header and item.is_installed

    @Property(str, notify=selectionChanged)
    def selectedVersion(self):
        item = self._version_model.get(self._selected)
        return item.display if item else ""

    @Property(bool, notify=selectionChanged)
    def selectedIsPrerelease(self):
        item = self._version_model.get(self._selected)
        return item.is_prerelease if item else False

    @Property(bool, notify=geoipChanged)
    def geoipAvailable(self):
        return self._geoip_available

    @Property(list, notify=geoipChanged)
    def geoipSources(self):
        return self._geoip_sources

    @Property(str, notify=geoipChanged)
    def geoipInstalled(self):
        return self._geoip_installed

    @Property(list, notify=geoipChanged)
    def geoipDownloaded(self):
        return self._geoip_downloaded

    @Property(str, notify=geoipChanged)
    def geoipPath(self):
        return self._geoip_path

    @Property(str, notify=geoipChanged)
    def geoipSize(self):
        return self._geoip_size

    @Property(str, notify=geoipChanged)
    def geoipMtime(self):
        return self._geoip_mtime

    @Property(bool, notify=geoipChanged)
    def geoipBusy(self):
        return self._geoip_busy

    @Property(float, notify=geoipChanged)
    def geoipProgress(self):
        return self._geoip_progress

    @Property(str, notify=geoipChanged)
    def lookupResult(self):
        return self._lookup_result

    @Property(bool, notify=geoipChanged)
    def lookupSuccess(self):
        return self._lookup_ok

    @Property(str, notify=infoChanged)
    def activeBrowserText(self):
        cfg = load_config()
        if cfg.get('pinned'):
            return f"v{cfg['pinned']}"
        channel = cfg.get('channel') or get_default_channel()
        _, keys, latest = self._build_channels()
        try:
            return latest[keys.index(channel)] or channel
        except ValueError:
            return channel

    @Property(str, notify=infoChanged)
    def activeBrowserColor(self):
        return "#26a69a"

    @Property(str, notify=infoChanged)
    def followedChannel(self):
        return load_config().get('channel') or get_default_channel()

    @Property(list, notify=infoChanged)
    def channels(self):
        return self._build_channels()[0]

    @Property(list, notify=infoChanged)
    def channelKeys(self):
        return self._build_channels()[1]

    @Property(list, notify=infoChanged)
    def channelLatest(self):
        return self._build_channels()[2]

    @Property(str, notify=infoChanged)
    def activeBrowserLabel(self):
        cfg = load_config()
        return "Pinned Version" if cfg.get('pinned') else "Active Channel"

    @Property(str, notify=infoChanged)
    def activeLabel(self):
        cfg = load_config()
        pinned = cfg.get('pinned')
        if pinned:
            return f"Pinned version: v{pinned}"
        channel = cfg.get('channel') or get_default_channel()
        parts = channel.split('/', 1)
        repo = parts[0].capitalize()
        ctype = parts[1] if len(parts) > 1 else 'stable'
        if ctype == 'stable':
            return f"Following channel: {repo}"
        return f"Following channel: {repo}/{ctype}"

    @Property(str, notify=infoChanged)
    def libraryVersion(self):
        return self._pkg_version('camoufox')

    @Property(str, notify=infoChanged)
    def playwrightVersion(self):
        return self._pkg_version('playwright')

    @Property(str, notify=infoChanged)
    def browserforgeVersion(self):
        return self._pkg_version('browserforge')

    @Property(str, notify=infoChanged)
    def fingerprintVersion(self):
        return self._pkg_version('apify_fingerprint_datapoints')

    @Property(str, notify=infoChanged)
    def lastSyncTime(self):
        cache = load_repo_cache()
        raw = cache.get('sync_time') if cache else None
        if not raw:
            return ""
        try:
            from datetime import datetime

            dt = datetime.strptime(raw, '%Y-%m-%d %H:%M')
            _dfmt = '%#m/%#d/%Y %#I:%M %p' if sys.platform == 'win32' else '%-m/%-d/%Y %-I:%M %p'
            return dt.strftime(_dfmt)
        except ValueError:
            return raw

    @Property(str, notify=infoChanged)
    def reposInfo(self):
        cache = load_repo_cache()
        if not cache:
            return "Run sync"
        repos = cache.get('repos', [])
        total = sum(len(r.get('versions', [])) for r in repos)
        return f"{len(repos)} repos, {total} versions"

    @Property(list, constant=True)
    def spoofOsOptions(self):
        return OS_OPTIONS

    @Property(list, constant=True)
    def spoofArchOptions(self):
        return ARCH_OPTIONS

    @Property(int, notify=debugChanged)
    def spoofOsIndex(self):
        return self._spoof_os_idx

    @Property(int, notify=debugChanged)
    def spoofArchIndex(self):
        return self._spoof_arch_idx

    @Property(str, notify=debugChanged)
    def spoofLibVer(self):
        return self._spoof_lib_ver

    @Property(int, notify=currentRepoChanged)
    def currentRepoIndex(self):
        if self._current_repo:
            for i, rc in enumerate(self._repo_configs):
                if rc.name == self._current_repo.name:
                    return i
        return 0

    # Internal

    @staticmethod
    def _pkg_version(pkg):
        try:
            from importlib.metadata import version

            return version(pkg)
        except Exception:
            return "?"

    def _build_channels(self):
        """
        Build channel names, keys, and latest version strings (cached)
        """
        if self._channel_data is not None:
            return self._channel_data

        cache = load_repo_cache()
        channels, keys, latest = [], [], []

        for rc in self._repo_configs:
            repo_versions = []
            if cache:
                for repo in cache.get('repos', []):
                    if repo['name'].lower() == rc.name.lower():
                        repo_versions = repo.get('versions', [])
                        break

            stable = [v for v in repo_versions if not v.get('is_prerelease')]
            prereleases = [v for v in repo_versions if v.get('is_prerelease')]

            channels.append(rc.name)
            keys.append(rc.name)
            latest.append(f"v{stable[0]['version']}-{stable[0]['build']}" if stable else "")

            if prereleases:
                channels.append(f"{rc.name} (Prerelease)")
                keys.append(f"{rc.name}/prerelease")
                latest.append(f"v{prereleases[0]['version']}-{prereleases[0]['build']}")

        self._channel_data = (channels, keys, latest)
        return self._channel_data

    # Slots

    @Slot(int)
    def selectRepo(self, index):
        if 0 <= index < len(self._repo_configs):
            self._current_repo = self._repo_configs[index]
            self._refresh()

    @Slot(bool)
    def setInstalledOnly(self, value):
        self._installed_only = value
        self._refresh()

    @Slot(str)
    def toggleSection(self, section):
        self._sections[section] = not self._sections.get(section, True)
        self._refresh()

    @Slot(int)
    def selectVersion(self, index):
        self._selected = index
        self.selectionChanged.emit()

    @Slot(int)
    def setActive(self, index):
        item = self._version_model.get(index)
        if not item or item.is_header:
            return

        cfg = load_config()
        cfg.pop('channel', None)
        cfg['pinned'] = f"{item.version_data.version.version}-{item.version_data.version.build}"
        cfg.update({
            'active_repo': self._current_repo.name,
            'active_build': item.version_data.version.build,
            'active_version': item.version_data.version.version,
        })
        save_config(cfg)

        if item.installed_data:
            set_active(item.installed_data.relative_path)

        self._refresh()
        self.infoChanged.emit()

    @Slot(int)
    def setFollowedChannel(self, index):
        _, keys, _ = self._build_channels()
        if not (0 <= index < len(keys)):
            return

        key = keys[index]
        cfg = load_config()
        cfg['channel'] = key
        cfg.pop('pinned', None)

        repo_name, ctype = (key.split('/', 1) + ['stable'])[:2]
        is_pre = ctype == 'prerelease'
        display, build = "", ""
        cache = load_repo_cache()
        if cache:
            for repo in cache.get('repos', []):
                if repo['name'].lower() == repo_name.lower():
                    candidates = [
                        v for v in repo.get('versions', [])
                        if v.get('is_prerelease') == is_pre
                    ]
                    if candidates:
                        cfg['active_build'] = candidates[0]['build']
                        cfg['active_version'] = candidates[0]['version']
                        cfg['active_repo'] = repo_name
                        display = f"v{candidates[0]['version']}"
                        build = candidates[0]['build']
                    break

        if not display:
            return

        # Send everything to pending until the prompt closes
        self._pending_channel = (cfg, repo_name, is_pre)
        self.channelPrompt.emit(-1, display, build)

    @Slot()
    def confirmFollowChannel(self):
        if self._pending_channel is None:
            return
        cfg, repo_name, is_pre = self._pending_channel
        self._pending_channel = None
        save_config(cfg)

        for rc in self._repo_configs:
            if rc.name.lower() == repo_name.lower():
                self._current_repo = rc
                self.currentRepoChanged.emit()
                break

        self._refresh()
        self.infoChanged.emit()

        for idx, item in enumerate(self._version_model._items):
            if item.is_header:
                continue
            if item.is_prerelease == is_pre:
                self._selected = idx
                self.selectionChanged.emit()
                if item.installed_data:
                    set_active(item.installed_data.relative_path)
                break

    @Slot()
    def installSelected(self):
        item = self._version_model.get(self._selected)
        if item and not item.is_header and not item.is_installed:
            self._run_worker(DownloadWorker(self._current_repo, item.version_data), self._on_done)

    @Slot()
    def uninstallSelected(self):
        item = self._version_model.get(self._selected)
        if not item or not item.is_installed or not item.installed_data:
            return
        try:
            remove_version(item.installed_data.path)
            self._set_status(f"Uninstalled {item.display}", "#2ecc71")
            self._refresh()
            self.infoChanged.emit()
        except Exception as e:
            self._set_status(str(e), "#e74c3c")

    @Slot()
    def refresh(self):
        self._refresh()
        self._set_status("Refreshed", "#888")

    @Slot()
    def sync(self):
        spoof_os = OS_OPTIONS[self._spoof_os_idx] if self._spoof_os_idx > 0 else None
        spoof_arch = ARCH_OPTIONS[self._spoof_arch_idx] if self._spoof_arch_idx > 0 else None
        spoof_lib = self._spoof_lib_ver or None
        self._run_worker(SyncWorker(spoof_os, spoof_arch, spoof_lib), self._on_done)

    @Slot()
    def cancelOperation(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
            self._busy = False
            self._progress = -1
            self.busyChanged.emit()
            self._set_status("Cancelled", "#f39c12")

    @Slot(str)
    def downloadGeoip(self, source):
        if not self._geoip_names or source not in self._geoip_names:
            return
        if source == self._geoip_installed:
            from ..geolocation import needs_update

            if not needs_update():
                return
        self._start_geoip_download(source)

    @Slot()
    def refreshGeoip(self):
        if self._geoip_installed:
            self._start_geoip_download(self._geoip_installed)

    @Slot()
    def deleteGeoipData(self):
        from ..geolocation import remove_mmdb

        remove_mmdb()
        self._load_geoip()

    @Slot(str)
    def deleteGeoipSource(self, source):
        from ..geolocation import MMDB_DIR, _get_geoip_config_by_name

        try:
            name = _get_geoip_config_by_name(source)['name'].lower()
            for f in MMDB_DIR.glob(f"{name}-*.mmdb"):
                f.unlink()
        except Exception:
            pass
        self._load_geoip()

    @Slot(str)
    def setActiveGeoip(self, source):
        from ..geolocation import _get_geoip_config_by_name, save_geoip_config

        if source not in self._geoip_downloaded:
            return
        save_geoip_config(_get_geoip_config_by_name(source))
        self._load_geoip()

    @Slot(int)
    def setSpoofOs(self, index):
        self._spoof_os_idx = index
        self.debugChanged.emit()

    @Slot(int)
    def setSpoofArch(self, index):
        self._spoof_arch_idx = index
        self.debugChanged.emit()

    @Slot(str)
    def setSpoofLibVer(self, ver):
        self._spoof_lib_ver = ver.strip()
        self.debugChanged.emit()

    @Slot()
    def openGeoipFolder(self):
        from ..geolocation import MMDB_DIR

        if not MMDB_DIR.exists():
            return

        import subprocess

        path = str(MMDB_DIR)
        if sys.platform == 'win32':
            subprocess.Popen(['explorer', path])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])

    @Slot(str)
    def lookupIp(self, ip):
        if not ip.strip():
            self._lookup_result = "Enter IP"
            self._lookup_ok = False
            self.geoipChanged.emit()
            return

        try:
            from ..geolocation import get_geolocation, get_mmdb_path

            if not get_mmdb_path().exists():
                self._lookup_result = "Database not downloaded"
                self._lookup_ok = False
                self.geoipChanged.emit()
                return

            geo = get_geolocation(ip.strip())
            self._lookup_result = "<br>".join([
                f"<b>Country:</b> {geo.locale.region}",
                f"<b>TZ:</b> {geo.timezone}",
                f"<b>Lat/Lon:</b> {geo.latitude:.4f}, {geo.longitude:.4f}",
            ])
            self._lookup_ok = True
        except Exception as e:
            self._lookup_result = str(e)
            self._lookup_ok = False

        self.geoipChanged.emit()

    # Internal helpers

    def _load_geoip(self):
        self._geoip_installed = ""
        self._geoip_downloaded = []
        self._geoip_path = ""
        self._geoip_size = ""
        self._geoip_mtime = ""

        try:
            from ..geolocation import (
                ALLOW_GEOIP,
                MMDB_DIR,
                _load_geoip_repos,
                get_mmdb_path,
                load_geoip_config,
            )

            if not ALLOW_GEOIP:
                self._geoip_available = False
                self.geoipChanged.emit()
                return

            self._geoip_available = True
            repos, _ = _load_geoip_repos()
            self._geoip_names = self._geoip_sources = [r.get('name', '?') for r in repos]

            if MMDB_DIR.exists():
                for repo in repos:
                    nm = repo.get('name', '').lower()
                    if (MMDB_DIR / f"{nm}-combined.mmdb").exists() or \
                       (MMDB_DIR / f"{nm}-ipv4.mmdb").exists():
                        self._geoip_downloaded.append(repo.get('name', ''))

            config = load_geoip_config()
            path = get_mmdb_path('ipv4', config)
            if path.exists():
                from datetime import datetime

                self._geoip_installed = config.get('name', '')
                self._geoip_path = str(path.parent)
                stat = path.stat()
                size = stat.st_size
                if 'combined' not in config.get('urls', {}):
                    ipv6 = get_mmdb_path('ipv6', config)
                    if ipv6.exists():
                        size += ipv6.stat().st_size
                self._geoip_size = f"{size / (1024 * 1024):.1f} MB"
                self._geoip_mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
                    '%Y-%m-%d %H:%M'
                )
        except Exception:
            pass

        self.geoipChanged.emit()

    def _load_spoof_from_cache(self):
        cache = load_repo_cache()
        if not cache:
            return
        spoof_os = cache.get('spoof_os')
        spoof_arch = cache.get('spoof_arch')
        spoof_lib = cache.get('spoof_lib_ver')
        if spoof_os and spoof_os in OS_OPTIONS:
            self._spoof_os_idx = OS_OPTIONS.index(spoof_os)
        if spoof_arch and spoof_arch in ARCH_OPTIONS:
            self._spoof_arch_idx = ARCH_OPTIONS.index(spoof_arch)
        if spoof_lib:
            self._spoof_lib_ver = spoof_lib

    def _refresh(self):
        items = []
        self._selected = -1

        if not self._current_repo:
            self._version_model.set_items(items)
            return

        installed = {v.version.build: v for v in list_installed()}
        cfg = load_config()
        active = cfg.get('active_build')
        pinned = cfg.get('pinned')
        versions = get_cached_versions(self._current_repo.name)

        if not versions:
            self._version_model.set_items(items)
            return

        for section, is_prerelease in [("stable", False), ("prerelease", True)]:
            version_list = [v for v in versions if v.is_prerelease == is_prerelease]
            if not version_list:
                continue

            expanded = self._sections.get(section, True)
            items.append(VersionItem(
                section.capitalize(), is_header=True,
                is_prerelease=is_prerelease, section=section, expanded=expanded,
            ))

            if expanded:
                for v in version_list:
                    inst = installed.get(v.version.build)
                    if self._installed_only and not inst:
                        continue
                    items.append(VersionItem(
                        f"v{v.version.version}", v.version.build,
                        is_prerelease=is_prerelease,
                        is_active=(active == v.version.build),
                        is_pinned=(pinned == v.version.full_string if pinned else False),
                        is_installed=bool(inst),
                        version_data=v, installed_data=inst,
                    ))

        self._version_model.set_items(items)
        self.selectionChanged.emit()

    def _set_status(self, text, color):
        self._status_text = text
        self._status_color = color
        self.statusChanged.emit()

    def _on_worker_progress(self, value):
        self._progress = value
        self.progressChanged.emit()

    def _on_worker_status(self, status):
        self._set_status(status, "#3498db")

    def _on_geoip_progress(self, value):
        self._geoip_progress = value
        self.geoipChanged.emit()

    def _on_geoip_status(self, status):
        self.geoipChanged.emit()

    def _run_worker(self, worker, done_callback):
        self._busy = True
        self._progress = -1
        self.busyChanged.emit()
        self._worker = worker
        worker.progress.connect(self._on_worker_progress)
        worker.status.connect(self._on_worker_status)
        worker.done.connect(done_callback)
        worker.start()

    def _on_done(self, ok, msg):
        self._busy = False
        self._progress = -1
        self.busyChanged.emit()
        self._set_status(msg if ok else f"Error: {msg}", "#2ecc71" if ok else "#e74c3c")
        if ok:
            self._channel_data = None
            self._refresh()
            self.infoChanged.emit()
            self._load_spoof_from_cache()
            self.debugChanged.emit()

    def _on_geoip_done(self, ok, msg):
        self._geoip_busy = False
        self._geoip_progress = -1
        self._load_geoip()

    def _start_geoip_download(self, source):
        self._geoip_busy = True
        self._geoip_progress = -1
        self.geoipChanged.emit()
        self._worker = GeoIPWorker(source)
        self._worker.progress.connect(self._on_geoip_progress)
        self._worker.status.connect(self._on_geoip_status)
        self._worker.done.connect(self._on_geoip_done)
        self._worker.start()


def main(debug=False):
    QQuickStyle.setStyle("Basic")

    # Suppress Breeze style warnings on KDE
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def _msg_filter(mode, ctx, msg):
        if 'org/kde/breeze' in msg:
            return
        if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            print(msg, file=sys.stderr)

    qInstallMessageHandler(_msg_filter)

    app = QGuiApplication(sys.argv)
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/icon.ico")))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("debugMode", debug)

    backend = Backend()
    backend.setParent(engine)
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml/main.qml")))

    if not engine.rootObjects():
        sys.exit(-1)

    ret = app.exec()
    del engine
    sys.exit(ret)
