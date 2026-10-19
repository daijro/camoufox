"""Regression coverage for raising the supported browser floor.

Raising ``CONSTRAINTS.MIN_VERSION`` is how the library forces an existing
install to upgrade when it can no longer talk to the old browser. That path
had been dead since the floor was dropped to ``alpha.1``, and it hid a bug:
``camoufox_path`` probed ``INSTALL_DIR/version.json``, which only the
pre-multiversion flat layout ever wrote, so a below-floor versioned install
raised ``FileNotFoundError`` instead of falling through to a fetch.
"""

import json

import pytest

from camoufox import multiversion, pkgman
from camoufox.exceptions import UnsupportedVersion


def _install(tmp_path, monkeypatch, layout, build, floor):
    """Build an install dir in the given layout and point the library at it."""
    root = tmp_path / "cache"
    root.mkdir()
    (root / ".0.5_FLAG").write_text("")
    (root / "repo_cache.json").write_text("{}")

    if layout == "versioned":
        relative = f"browsers/official/152.0.4-{build}"
        (root / "config.json").write_text(json.dumps({"active_version": relative}))
        version_dir = root / relative
        version_dir.mkdir(parents=True)
    else:
        (root / "config.json").write_text("{}")
        version_dir = root
    (version_dir / "version.json").write_text(
        json.dumps({"version": "152.0.4", "build": build})
    )

    for module in (pkgman, multiversion):
        monkeypatch.setattr(module, "INSTALL_DIR", root)
    monkeypatch.setattr(multiversion, "BROWSERS_DIR", root / "browsers")
    monkeypatch.setattr(multiversion, "CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(multiversion, "COMPAT_FLAG", root / ".0.5_FLAG")
    monkeypatch.setattr(pkgman, "VERSION_MIN", pkgman.Version(build=floor))
    return root


@pytest.mark.parametrize("layout", ["versioned", "legacy"])
def test_below_floor_install_is_reported_as_outdated(tmp_path, monkeypatch, layout):
    """A build under the floor must report as outdated, never as missing."""
    _install(tmp_path, monkeypatch, layout, build="beta.29", floor="beta.30")

    with pytest.raises(UnsupportedVersion):
        pkgman.camoufox_path(download_if_missing=False)


@pytest.mark.parametrize("layout", ["versioned", "legacy"])
def test_at_floor_install_is_kept(tmp_path, monkeypatch, layout):
    """A build at the floor is still served, in either layout."""
    root = _install(tmp_path, monkeypatch, layout, build="beta.30", floor="beta.30")

    resolved = pkgman.camoufox_path(download_if_missing=False)

    expected = root if layout == "legacy" else root / "browsers/official/152.0.4-beta.30"
    assert resolved == expected


def test_below_floor_install_triggers_a_fetch(tmp_path, monkeypatch):
    """The default path upgrades the install instead of raising."""
    root = _install(tmp_path, monkeypatch, "versioned", build="beta.29", floor="beta.30")
    installed = []

    class StubFetcher:
        def install(self):
            installed.append(True)
            relative = "browsers/official/152.0.4-beta.30"
            version_dir = root / relative
            version_dir.mkdir(parents=True)
            (version_dir / "version.json").write_text(
                json.dumps({"version": "152.0.4", "build": "beta.30"})
            )
            (root / "config.json").write_text(json.dumps({"active_version": relative}))

    monkeypatch.setattr(pkgman, "CamoufoxFetcher", StubFetcher)

    resolved = pkgman.camoufox_path()

    assert installed == [True]
    assert resolved == root / "browsers/official/152.0.4-beta.30"


def test_root_probe_tolerates_the_versioned_layout(tmp_path, monkeypatch):
    """The root probe reports False, rather than raising, with no root file."""
    root = tmp_path / "cache"
    root.mkdir()
    monkeypatch.setattr(pkgman, "INSTALL_DIR", root)

    assert pkgman._root_install_supported() is False


def test_unsatisfiable_floor_reports_instead_of_recursing(tmp_path, monkeypatch):
    """A floor no published build satisfies must report, not spin.

    install() is a no-op when the newest release is already installed, so the
    old `return camoufox_path()` tail recursed ~1000 times -- each iteration
    firing another GitHub API call, which exhausts the unauthenticated rate
    limit long before the RecursionError lands. That is the state a library
    published ahead of its browser release puts every user in.
    """
    _install(tmp_path, monkeypatch, "versioned", build="beta.29", floor="beta.30")
    attempts = []

    class StubFetcher:
        def install(self):
            attempts.append(True)  # newest published build is still below the floor

    monkeypatch.setattr(pkgman, "CamoufoxFetcher", StubFetcher)

    with pytest.raises(UnsupportedVersion):
        pkgman.camoufox_path()

    assert attempts == [True], "should fetch once, not spin"


class TestConditionalFloor:
    """The browser floor is keyed on the resolved Playwright, not fixed.

    A flat floor can only speak about the browser, so to be safe it has to
    assume the worst Playwright and re-download for everyone -- and it makes
    the library unusable until the matching browser release exists. Keyed on
    Playwright, only the pairing that actually breaks gets moved.
    """

    @staticmethod
    def _with_playwright(monkeypatch, version):
        parsed = pkgman._parse_semver(version) if version else None
        monkeypatch.setattr(pkgman, "_resolved_playwright_version", lambda: parsed)

    @pytest.mark.parametrize("version", ["1.53.0", "1.60.0"])
    def test_old_playwright_leaves_older_builds_alone(self, monkeypatch, version):
        """<1.61 never sends the fields beta.29 rejects, so nothing must move."""
        self._with_playwright(monkeypatch, version)
        assert pkgman.effective_version_min() == pkgman.Version(build="alpha.1")

    @pytest.mark.parametrize("version", ["1.61.0", "1.62.0"])
    def test_new_playwright_raises_the_floor(self, monkeypatch, version):
        self._with_playwright(monkeypatch, version)
        assert pkgman.effective_version_min() == pkgman.Version(build="beta.30")

    def test_unreadable_playwright_falls_back_permissive(self, monkeypatch):
        """A spurious forced re-download is worse than leaving a working install."""
        self._with_playwright(monkeypatch, None)
        assert pkgman.effective_version_min() == pkgman.Version(build="alpha.1")

    def test_old_playwright_keeps_a_below_floor_install(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, "versioned", build="beta.29", floor="alpha.1")
        self._with_playwright(monkeypatch, "1.60.0")

        resolved = pkgman.camoufox_path(download_if_missing=False)

        assert resolved.name == "152.0.4-beta.29"

    def test_new_playwright_moves_a_below_floor_install(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, "versioned", build="beta.29", floor="alpha.1")
        self._with_playwright(monkeypatch, "1.62.0")

        with pytest.raises(UnsupportedVersion):
            pkgman.camoufox_path(download_if_missing=False)
