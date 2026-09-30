"""Every GeoIP source camoufox offers must be serving a current build.

The launcher always downloads a source's newest build, so a source that stops
publishing leaves every user on stale data with no error: GeoLite2's URLs
served the 2026-06-17 build for months after sapics/ip-location-db moved to
GitHub Releases (found in daijro/camoufox#815, which this test comes from).
This suite runs in tests.yml, which gates every release.
"""

import time

import pytest

from camoufox import geolocation

maxminddb = pytest.importorskip("maxminddb")

MAX_AGE_DAYS = 30

SOURCES = [repo["name"] for repo in geolocation._load_geoip_repos()[0] if not repo.get("deprecated")]


@pytest.mark.parametrize("name", SOURCES)
def test_source_serves_a_current_build(name, tmp_path, monkeypatch):
    monkeypatch.setattr(geolocation, "GEOIP_DIR", tmp_path)
    monkeypatch.setattr(geolocation, "MMDB_DIR", tmp_path / "mmdb")
    monkeypatch.setattr(geolocation, "GEOIP_CONFIG", tmp_path / "config.yml")

    geolocation.download_mmdb(name)

    databases = sorted((tmp_path / "mmdb").glob("*.mmdb"))
    assert databases, f"{name} downloaded no database"
    for database in databases:
        with maxminddb.open_database(str(database)) as reader:
            age_days = (time.time() - reader.metadata().build_epoch) / 86400
            record = reader.get("8.8.8.8")
        assert age_days < MAX_AGE_DAYS, (
            f"{name}: {database.name} was built {age_days:.0f} days ago, its source is no longer updated"
        )
        config = geolocation._get_geoip_config_by_name(name)
        assert geolocation._find_in(record, config["paths"]["iso_code"]) == "US", (
            f"{name}: the configured paths do not read this database"
        )
