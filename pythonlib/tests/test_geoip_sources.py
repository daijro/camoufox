import time
import maxminddb
import pytest

from camoufox import geolocation

MAX_AGE_DAYS = 30

SOURCES = [repo["name"] for repo in geolocation._load_geoip_repos()[0]]


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
        assert age_days < MAX_AGE_DAYS, (
            f"{name}: {database.name} was built {age_days:.0f} days ago, its source is no longer updated"
        )
