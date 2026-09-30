"""Which GeoIP source is active, and when its database is refreshed."""

import os
import time
import warnings

import pytest
from yaml import safe_dump

from camoufox import geolocation

DEFAULT = "GeoIP AIO by daijro"
DEPRECATED = "MaxMind GeoLite2"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(geolocation, "GEOIP_DIR", tmp_path)
    monkeypatch.setattr(geolocation, "MMDB_DIR", tmp_path / "mmdb")
    monkeypatch.setattr(geolocation, "GEOIP_CONFIG", tmp_path / "config.yml")
    return tmp_path


def _saved(cache, **fields):
    (cache / "config.yml").write_text(safe_dump(fields))


def test_default_is_aio():
    assert geolocation.load_geoip_config()["name"] == DEFAULT
    repos, _ = geolocation._load_geoip_repos()
    assert [r["name"] for r in repos if r.get("deprecated")] == [DEPRECATED]


def test_implicit_deprecated_source_moves_to_default(cache):
    # What every cache written before the default changed holds
    _saved(cache, name=DEPRECATED)
    assert geolocation.load_geoip_config()["name"] == DEFAULT


def test_explicit_deprecated_source_is_kept(cache):
    _saved(cache, name=DEPRECATED, explicit=True)
    assert geolocation.load_geoip_config()["name"] == DEPRECATED


def test_save_records_explicit_choice(cache):
    config = geolocation._get_geoip_config_by_name(DEPRECATED)
    geolocation.save_geoip_config(config, explicit=True)
    assert geolocation.load_geoip_config()["name"] == DEPRECATED
    geolocation.save_geoip_config(config)
    assert geolocation.load_geoip_config()["name"] == DEFAULT


def test_refresh_keeps_an_explicit_choice(cache, monkeypatch):
    # `camoufox fetch` and the weekly refresh download without naming a source
    _saved(cache, name=DEPRECATED, explicit=True)
    monkeypatch.setattr(geolocation, "webdl", lambda url, buffer, **kw: buffer.write(b"x"))
    monkeypatch.setattr(geolocation, "_build_age_days", lambda path: 1)
    geolocation.download_mmdb()
    assert geolocation.load_geoip_config()["name"] == DEPRECATED


def test_deprecated_source_warns():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        geolocation.warn_if_deprecated(geolocation._get_geoip_config_by_name(DEPRECATED))
        geolocation.warn_if_deprecated(geolocation._get_geoip_config_by_name(DEFAULT))
    assert [w.category for w in caught] == [FutureWarning]
    assert DEFAULT in str(caught[0].message)


def _database(cache, checked_days_ago):
    config = geolocation.load_geoip_config()
    path = geolocation.get_mmdb_path("ipv4", config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    stamp = time.time() - checked_days_ago * 86400
    os.utime(path, (stamp, stamp))
    return config


@pytest.mark.parametrize(
    "checked, built, stale",
    [
        (0.5, 400, False),  # checked today: wait, even for an old build
        (2, 3, False),  # this week's build
        (2, 9, True),  # a release has been missed
        (40, 3, False),  # an old file holding a new build is not stale
        (2, None, True),  # unreadable database
    ],
)
def test_needs_update_reads_the_build_date(cache, monkeypatch, checked, built, stale):
    config = _database(cache, checked)
    monkeypatch.setattr(geolocation, "_build_age_days", lambda path: built)
    assert geolocation.needs_update(config) is stale


def test_missing_database_needs_update():
    assert geolocation.needs_update() is True
