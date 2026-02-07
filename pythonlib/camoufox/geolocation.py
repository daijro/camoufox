"""
Helpers to fetch geolocation, timezone, and locale data given an IP
"""

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from platformdirs import user_cache_dir
from yaml import CDumper, CLoader
from yaml import dump as yaml_dump
from yaml import load as yaml_load

from .exceptions import NotInstalledGeoIPExtra, UnknownIPLocation
from .ip import validate_ip
from .locale import SELECTOR, Geolocation
from .pkgman import LOCAL_DATA, rprint, unzip, webdl

try:
    import maxminddb  # type: ignore
except ImportError:
    ALLOW_GEOIP = False
else:
    ALLOW_GEOIP = True


GEOIP_DIR = Path(user_cache_dir("camoufox")) / "geoip"
MMDB_DIR = GEOIP_DIR / "mmdb"
GEOIP_CONFIG = GEOIP_DIR / "config.yml"


def _find_in(data: Dict, key: str) -> Any:
    """
    Resolve a dotted path in a nested dict
    """
    for part in key.split('.'):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
        if data is None:
            return None
    return data


def _load_geoip_repos() -> Tuple[List[Dict], str]:
    """
    Load GeoIP repos and default name from repos.yml
    """
    with open(LOCAL_DATA / 'repos.yml', 'r') as f:
        data = yaml_load(f, Loader=CLoader)
    geoip_repos = data.get('geoip', [])
    default_name = data.get('default', {}).get('geoip', 'GeoLite2')
    return geoip_repos, default_name


def _get_geoip_config_by_name(name: Optional[str] = None) -> Dict:
    """
    Get GeoIP config by name from repos.yml. If None, uses default
    """
    repos, default_name = _load_geoip_repos()
    target_name = name or default_name

    def _validate_repo(repo: Dict) -> Dict:
        if 'urls' not in repo:
            raise ValueError(f"GeoIP repo '{repo.get('name')}' missing required urls")
        if 'paths' not in repo:
            raise ValueError(f"GeoIP repo '{repo.get('name')}' missing required paths")
        return repo

    for repo in repos:
        if repo.get('name', '').lower() == target_name.lower():
            return _validate_repo(repo)

    if name:
        available = [r.get('name', 'Unknown') for r in repos]
        raise ValueError(f"GeoIP database '{name}' not found. Available: {available}")

    if repos:
        return _validate_repo(repos[0])
    raise ValueError("No GeoIP repos configured in repos.yml")


def load_geoip_config() -> Dict:
    """
    Load active GeoIP config from disk, falling back to repos.yml default
    """
    if GEOIP_CONFIG.exists():
        with open(GEOIP_CONFIG, 'r') as f:
            saved = yaml_load(f, Loader=CLoader)
        try:
            return _get_geoip_config_by_name(saved.get('name'))
        except (ValueError, KeyError):
            return saved
    return _get_geoip_config_by_name(None)


def save_geoip_config(config: Dict) -> None:
    """
    Save active GeoIP source name to disk
    """
    GEOIP_DIR.mkdir(parents=True, exist_ok=True)
    with open(GEOIP_CONFIG, 'w') as f:
        yaml_dump({'name': config['name']}, f, Dumper=CDumper, default_flow_style=False)


def get_mmdb_path(ip_version: str = 'ipv4', config: Optional[Dict] = None) -> Path:
    """
    Get path to the mmdb file for the specified IP version
    """
    if config is None:
        config = load_geoip_config()
    name = config.get('name', 'geolite2').lower()
    urls = config.get('urls', {})
    if 'combined' in urls:
        return MMDB_DIR / f"{name}-combined.mmdb"
    return MMDB_DIR / f"{name}-{ip_version}.mmdb"


def geoip_allowed() -> None:
    """
    Checks if the geoip2 module is available
    """
    if not ALLOW_GEOIP:
        raise NotInstalledGeoIPExtra(
            'Please install the geoip extra to use this feature: pip install camoufox[geoip]'
        )


def download_mmdb(
    source: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> None:
    """
    Downloads the GeoIP database(s) to geoip/mmdb/
    """
    geoip_allowed()

    config = _get_geoip_config_by_name(source) if source else load_geoip_config()
    urls = config['urls']
    name = config['name'].lower()

    MMDB_DIR.mkdir(parents=True, exist_ok=True)

    extract = config.get('extract', False)
    dl_desc = f'Downloading {config["name"]}'
    ex_desc = f'Extracting {config["name"]}'
    max_len = max(len(dl_desc), len(ex_desc))
    dl_desc = dl_desc.ljust(max_len)
    ex_desc = ex_desc.ljust(max_len)

    for ip_ver, url_list in urls.items():
        mmdb_path = MMDB_DIR / f"{name}-{ip_ver}.mmdb"

        if isinstance(url_list, str):
            url_list = [url_list]

        last_error = None
        for url in url_list:
            try:
                with tempfile.NamedTemporaryFile(suffix='.zip' if extract else '.mmdb') as tmp:
                    webdl(
                        url,
                        desc=dl_desc,
                        buffer=tmp,
                        bar=progress_callback is None,
                        progress_callback=progress_callback,
                    )
                    if extract:
                        with tempfile.TemporaryDirectory() as tmpdir:
                            unzip(tmp, tmpdir, desc=ex_desc, bar=progress_callback is None)
                            mmdb_files = list(Path(tmpdir).rglob('*.mmdb'))
                            if not mmdb_files:
                                raise ValueError("No .mmdb file found in archive")
                            shutil.move(str(mmdb_files[0]), str(mmdb_path))
                    else:
                        tmp.seek(0)
                        with open(mmdb_path, 'wb') as dst:
                            shutil.copyfileobj(tmp, dst)
                break
            except Exception as e:
                last_error = e
                continue
        else:
            raise last_error or Exception(f"Failed to download {ip_ver}")

    save_geoip_config(config)


def remove_mmdb() -> None:
    """
    Removes the GeoIP database and config
    """
    if not GEOIP_DIR.exists():
        rprint("GeoIP database not found.")
        return

    shutil.rmtree(GEOIP_DIR)
    rprint("GeoIP database removed.")


def needs_update(config: Optional[Dict] = None) -> bool:
    """
    Check if the GeoIP database needs an update (older than 30 days)
    """
    from datetime import datetime, timedelta

    if config is None:
        config = load_geoip_config()

    update_days = 30

    ipv4_path = get_mmdb_path('ipv4', config)
    if not ipv4_path.exists():
        return True

    mtime = datetime.fromtimestamp(ipv4_path.stat().st_mtime)
    age = datetime.now() - mtime
    return age > timedelta(days=update_days)


def get_geolocation(ip: str, geoip_db: Optional[str] = None) -> Geolocation:
    """
    Gets the geolocation for an IP address
    """
    import maxminddb

    validate_ip(ip)
    ip_version = 'ipv6' if ':' in ip else 'ipv4'
    mmdb_path = get_mmdb_path(ip_version)

    if not mmdb_path.exists() or needs_update():
        download_mmdb()
        mmdb_path = get_mmdb_path(ip_version)

    if geoip_db:
        config = _get_geoip_config_by_name(geoip_db)
    else:
        config = load_geoip_config()
    paths = config['paths']

    with maxminddb.open_database(str(mmdb_path)) as reader:
        resp = cast(Dict[str, Any], reader.get(ip))

        if not resp:
            raise UnknownIPLocation(f"IP not found in database: {ip}")

        iso_code = _find_in(resp, paths['iso_code'])
        longitude = _find_in(resp, paths['longitude'])
        latitude = _find_in(resp, paths['latitude'])
        timezone = _find_in(resp, paths['timezone'])

        iso_code = str(iso_code).upper()
        locale = SELECTOR.from_region(iso_code)

        return Geolocation(
            locale=locale,
            longitude=float(longitude),
            latitude=float(latitude),
            timezone=str(timezone),
        )
