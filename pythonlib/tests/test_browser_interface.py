"""A browser declares the interface it speaks; the library refuses one it cannot drive.

Every browser release carries `interface` in its manifest.json, taken from
CONSTRAINTS.INTERFACE in the tree it was built from, and the number rises only
when a browser change would break released libraries. #835 is what happens
without it: a library that accepts every build name downloads a browser it
cannot launch. These tests hold the three places that consult it -- choosing an
asset to download, listing versions for `camoufox sync`, and the active install
at launch -- to the range this library supports.
"""

import json
import warnings

import pytest

from camoufox import multiversion, pkgman
from camoufox.__version__ import CONSTRAINTS
from camoufox.exceptions import UnsupportedVersion

NEWER = CONSTRAINTS.INTERFACE + 1


@pytest.fixture
def manifests(monkeypatch):
    """Serve manifest.json bodies by URL, and record which were fetched."""
    served, fetched = {}, []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def get(url, **_kwargs):
        fetched.append(url)
        return Response(served[url])

    monkeypatch.setattr(pkgman.requests, "get", get)
    monkeypatch.setattr(pkgman, "_release_interfaces", {})
    return served, fetched


def _release(tag, build, manifest=None, served=None):
    assets = [{"name": f"camoufox-156.0.1-{build}-lin.x86_64.zip",
               "browser_download_url": f"https://example.invalid/{tag}/browser.zip"}]
    if manifest is not None:
        url = f"https://example.invalid/{tag}/manifest.json"
        served[url] = manifest
        assets.append({"name": "manifest.json", "id": tag, "browser_download_url": url})
    return {"tag_name": tag, "prerelease": False, "assets": assets}


def test_a_release_without_a_manifest_is_interface_1_and_fetches_nothing(manifests):
    _, fetched = manifests
    assert pkgman.release_interface(_release("v156.0.1-beta.31", "beta.31")) == 1
    assert fetched == []


def test_a_manifest_without_the_field_is_interface_1(manifests):
    served, _ = manifests
    release = _release("v156.0.1-beta.33", "beta.33", {"schema": 1}, served)
    assert pkgman.release_interface(release) == 1


def test_the_fetcher_skips_a_browser_this_library_cannot_drive(manifests, monkeypatch, capsys):
    served, _ = manifests
    monkeypatch.setattr("camoufox.browser_pin.effective_pin", lambda *a, **k: None)
    fetcher = pkgman.CamoufoxFetcher.__new__(pkgman.CamoufoxFetcher)
    fetcher.repo_config = pkgman.RepoConfig.get_default()
    fetcher.pattern = fetcher.repo_config.build_pattern(spoof_os="lin", spoof_arch="x86_64")
    fetcher.installed_sha256 = None
    fetcher.installed_created_at = None

    newer = _release("v156.0.1-beta.40", "beta.40", {"interface": NEWER}, served)
    current = _release("v156.0.1-beta.39", "beta.39", {"interface": CONSTRAINTS.INTERFACE}, served)

    assert fetcher.check_asset(newer["assets"][0], newer) is None
    assert "needs a newer camoufox package" in capsys.readouterr().out
    assert fetcher.check_asset(current["assets"][0], current) is not None
    assert fetcher.installed_interface == CONSTRAINTS.INTERFACE


def test_sync_lists_only_browsers_this_library_can_drive(manifests, monkeypatch):
    served, _ = manifests
    releases = [
        _release("v156.0.1-beta.40", "beta.40", {"interface": NEWER}, served),
        _release("v156.0.1-beta.39", "beta.39", {"interface": CONSTRAINTS.INTERFACE}, served),
        _release("v156.0.1-beta.31", "beta.31"),
    ]
    api = "https://api.github.com/repos/daijro/camoufox/releases"
    served[api] = releases

    versions = pkgman.list_available_versions(spoof_os="lin", spoof_arch="x86_64")

    assert [v.version.build for v in versions] == ["beta.39", "beta.31"]
    assert [v.interface for v in versions] == [CONSTRAINTS.INTERFACE, 1]


def _active_install(tmp_path, monkeypatch, interface):
    root = tmp_path / "cache"
    relative = "browsers/official/156.0.1-beta.40"
    (root / relative).mkdir(parents=True)
    (root / ".0.5_FLAG").write_text("")
    (root / "config.json").write_text(json.dumps({"active_version": relative}))
    metadata = {"version": "156.0.1", "build": "beta.40"}
    if interface is not None:
        metadata["interface"] = interface
    (root / relative / "version.json").write_text(json.dumps(metadata))
    for module in (pkgman, multiversion):
        monkeypatch.setattr(module, "INSTALL_DIR", root)
    monkeypatch.setattr(multiversion, "BROWSERS_DIR", root / "browsers")
    monkeypatch.setattr(multiversion, "CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(multiversion, "COMPAT_FLAG", root / ".0.5_FLAG")
    monkeypatch.setattr("camoufox.browser_pin.effective_pin", lambda *a, **k: None)
    return root / relative


def test_launch_refuses_an_installed_browser_this_library_cannot_drive(tmp_path, monkeypatch):
    _active_install(tmp_path, monkeypatch, NEWER)
    with pytest.raises(UnsupportedVersion, match="pip install -U camoufox"):
        pkgman.camoufox_path()


@pytest.mark.parametrize("interface", [None, CONSTRAINTS.INTERFACE])
def test_launch_keeps_a_browser_it_can_drive(tmp_path, monkeypatch, interface):
    """An install recorded before version.json carried the field is interface 1."""
    path = _active_install(tmp_path, monkeypatch, interface)
    assert pkgman.camoufox_path(download_if_missing=False) == path


def _synced(tmp_path, monkeypatch, incompatible):
    root = tmp_path / "cache"
    root.mkdir(exist_ok=True)
    cache = {"repos": [], "incompatible": incompatible}
    (root / "repo_cache.json").write_text(json.dumps(cache))
    monkeypatch.setattr(multiversion, "INSTALL_DIR", root)
    monkeypatch.setattr(multiversion, "REPO_CACHE_FILE", root / "repo_cache.json")
    monkeypatch.setattr(pkgman, "_outdated_warned", False)


def test_a_launch_warns_once_when_sync_found_a_browser_needing_an_upgrade(tmp_path, monkeypatch):
    _synced(tmp_path, monkeypatch, [
        {"repo": "Official", "version": "156.0.1", "build": "beta.40", "interface": NEWER},
        {"repo": "Official", "version": "156.0.1", "build": "beta.41", "interface": NEWER},
    ])
    with pytest.warns(RuntimeWarning, match=r"v156\.0\.1-beta\.41 needs a newer camoufox package.*pip install -U camoufox"):
        pkgman.warn_if_package_outdated()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pkgman.warn_if_package_outdated()  # once per process, not per launch


def test_no_warning_when_every_synced_browser_is_drivable(tmp_path, monkeypatch):
    _synced(tmp_path, monkeypatch, [])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pkgman.warn_if_package_outdated()


def test_sync_keeps_builds_needing_an_upgrade_out_of_the_installable_list(manifests, monkeypatch, tmp_path, capsys):
    from camoufox import __main__ as cli

    served, _ = manifests
    served["https://api.github.com/repos/daijro/camoufox/releases"] = [
        _release("v156.0.1-beta.40", "beta.40", {"interface": NEWER}, served),
        _release("v156.0.1-beta.39", "beta.39", {"interface": CONSTRAINTS.INTERFACE}, served),
    ]
    _synced(tmp_path, monkeypatch, [])
    official = pkgman.RepoConfig.get_default()
    monkeypatch.setattr(pkgman.RepoConfig, "load_repos", staticmethod(lambda: [official]))

    cli._do_sync(spoof_os="lin", spoof_arch="x86_64")

    cache = json.loads((tmp_path / "cache" / "repo_cache.json").read_text())
    assert [v["build"] for v in cache["repos"][0]["versions"]] == ["beta.39"]
    assert cache["incompatible"] == [
        {"repo": official.name, "version": "156.0.1", "build": "beta.40", "interface": NEWER}
    ]
    assert "v156.0.1-beta.40 needs a newer camoufox package" in capsys.readouterr().out
