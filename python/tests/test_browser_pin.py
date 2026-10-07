"""A released library runs the browser it was released with, and nothing else by default.

Each published package is stamped with `browser-pin.json` naming the browser
release built from the same sources. These tests hold the three places that
decide which build is used -- the active install at launch, the asset the
fetcher accepts, and the explicit-choice escape hatch -- to that pairing.
"""

import json
import warnings

import pytest

from camoufox import browser_pin, multiversion, pkgman
from camoufox.exceptions import CamoufoxNotInstalled

PIN = {
    "tag": "v156.0.1-beta.33",
    "repo": "daijro/camoufox",
    "repo_name": "Official",
    "version": "156.0.1",
    "build": "beta.33",
}


def _setup(tmp_path, monkeypatch, *, pin, installed, config):
    root = tmp_path / "cache"
    root.mkdir()
    (root / ".0.5_FLAG").write_text("")
    (root / "repo_cache.json").write_text("{}")
    (root / "config.json").write_text(json.dumps(config))
    for spec in installed:
        version, build = spec.split("-", 1)
        d = root / "browsers" / "official" / spec
        d.mkdir(parents=True)
        (d / "version.json").write_text(json.dumps({"version": version, "build": build}))
    pin_file = tmp_path / "browser-pin.json"
    pin_file.write_text(json.dumps(pin))
    monkeypatch.setattr(browser_pin, "PIN_FILE", pin_file)
    monkeypatch.setattr(browser_pin, "_warned", False)
    for module in (pkgman, multiversion):
        monkeypatch.setattr(module, "INSTALL_DIR", root)
    monkeypatch.setattr(multiversion, "BROWSERS_DIR", root / "browsers")
    monkeypatch.setattr(multiversion, "CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(multiversion, "COMPAT_FLAG", root / ".0.5_FLAG")
    return root


@pytest.mark.parametrize("content", ["{}", '{"tag": null}', "", "not json"])
def test_an_empty_or_missing_pin_pins_nothing(tmp_path, content):
    f = tmp_path / "browser-pin.json"
    f.write_text(content)
    assert browser_pin.load_pin(f) is None
    assert browser_pin.load_pin(tmp_path / "absent.json") is None


def test_the_checked_in_pin_is_empty():
    """main pins nothing; only the release workflow writes a real pin."""
    assert json.loads(browser_pin.PIN_FILE.read_text()) == {}


def test_launch_uses_the_paired_build_even_when_another_is_marked_active(tmp_path, monkeypatch):
    root = _setup(
        tmp_path, monkeypatch, pin=PIN,
        installed=["156.0.1-beta.33", "157.0-beta.34"],
        config={"active_version": "browsers/official/157.0-beta.34"},
    )
    assert multiversion.get_active_path() == root / "browsers/official/156.0.1-beta.33"
    assert pkgman.installed_verstr() == "156.0.1-beta.33"


def test_a_newer_build_is_not_used_when_the_paired_one_is_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pin=PIN, installed=["157.0-beta.34"], config={})
    assert multiversion.get_active_path() is None
    with pytest.raises(CamoufoxNotInstalled, match="156.0.1-beta.33"):
        pkgman.installed_verstr()


def test_an_explicit_choice_is_kept_and_warned_about(tmp_path, monkeypatch):
    root = _setup(
        tmp_path, monkeypatch, pin=PIN,
        installed=["156.0.1-beta.33", "157.0-beta.34"],
        config={"channel": "official/stable", "active_version": "browsers/official/157.0-beta.34"},
    )
    assert multiversion.get_active_path() == root / "browsers/official/157.0-beta.34"
    with pytest.warns(RuntimeWarning, match="v156.0.1-beta.33"):
        assert pkgman.installed_verstr() == "157.0-beta.34"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pkgman.installed_verstr()  # once per process, not per launch


def test_an_explicit_choice_of_the_paired_build_does_not_warn(tmp_path, monkeypatch):
    _setup(
        tmp_path, monkeypatch, pin=PIN, installed=["156.0.1-beta.33"],
        config={"pinned": "156.0.1-beta.33", "channel": "official/prerelease",
                "active_version": "browsers/official/156.0.1-beta.33"},
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert pkgman.installed_verstr() == "156.0.1-beta.33"


def test_without_a_pin_the_channel_logic_is_unchanged(tmp_path, monkeypatch):
    root = _setup(
        tmp_path, monkeypatch, pin={}, installed=["156.0.1-beta.33", "157.0-beta.34"],
        config={"active_version": "browsers/official/157.0-beta.34"},
    )
    assert multiversion.get_active_path() == root / "browsers/official/157.0-beta.34"


@pytest.mark.parametrize("config,accepts_newer", [({}, False), ({"channel": "official/stable"}, True)])
def test_the_fetcher_accepts_only_the_paired_asset_by_default(tmp_path, monkeypatch, config, accepts_newer):
    _setup(tmp_path, monkeypatch, pin=PIN, installed=[], config=config)
    fetcher = pkgman.CamoufoxFetcher.__new__(pkgman.CamoufoxFetcher)
    fetcher.repo_config = pkgman.RepoConfig.get_default()
    fetcher.pattern = fetcher.repo_config.build_pattern(spoof_os="lin", spoof_arch="x86_64")
    fetcher.installed_sha256 = None
    fetcher.installed_created_at = None

    def asset(version, build):
        return {"name": f"camoufox-{version}-{build}-lin.x86_64.zip",
                "browser_download_url": f"https://example.invalid/{version}-{build}.zip"}

    assert fetcher.check_asset(asset("156.0.1", "beta.33"), {"prerelease": True}) is not None
    newer = fetcher.check_asset(asset("157.0", "beta.34"), {"prerelease": False})
    assert (newer is not None) is accepts_newer


@pytest.mark.parametrize("raw,expected", [
    ("0.5.8", (0, 5, 8)),
    ("0.5.8b1", (0, 5, 8)),
    ("0.5.8rc2", (0, 5, 8)),
    ("0.5.8.dev3", (0, 5, 8)),
    ("0.5.8-beta.1", (0, 5, 8)),
    ("^0.5.0", (0, 5, 0)),
    ("1", (1, 0, 0)),
])
def test_prerelease_library_versions_parse_as_their_release(raw, expected):
    assert pkgman._parse_semver(raw) == expected


def test_a_missing_paired_build_is_reported_as_not_installed_not_outdated(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, pin=PIN, installed=["157.0-beta.34"], config={})
    with pytest.raises(CamoufoxNotInstalled, match="pairs with"):
        pkgman.camoufox_path(download_if_missing=False)
