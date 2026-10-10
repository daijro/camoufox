"""Regression coverage for the Linux runtime directory required at startup."""

import os

import pytest

from camoufox import multiversion, pkgman, utils


def test_missing_linux_profile_directory_is_created(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pkgman, "OS_NAME", "lin")

    profile_dir = pkgman.ensure_browser_profile_dir({"HOME": str(home)})

    assert profile_dir == home / ".camoufox"
    assert profile_dir.is_dir()


def test_existing_profile_directory_can_be_read_only(tmp_path, monkeypatch):
    home = tmp_path / "home"
    profile_dir = home / ".camoufox"
    profile_dir.mkdir(parents=True)
    monkeypatch.setattr(pkgman, "OS_NAME", "lin")
    home.chmod(0o500)
    profile_dir.chmod(0o500)
    try:
        assert pkgman.ensure_browser_profile_dir({"HOME": str(home)}) == profile_dir
    finally:
        profile_dir.chmod(0o700)
        home.chmod(0o700)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions required")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses directory permission bits",
)
def test_missing_profile_directory_in_read_only_home_fails_fast(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pkgman, "OS_NAME", "lin")
    home.chmod(0o500)
    try:
        with pytest.raises(RuntimeError, match=r"\.camoufox.*before.*read-only"):
            pkgman.ensure_browser_profile_dir({"HOME": str(home)})
    finally:
        home.chmod(0o700)


def test_other_platforms_do_not_create_linux_profile_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pkgman, "OS_NAME", "mac")

    assert pkgman.ensure_browser_profile_dir({"HOME": str(home)}) is None
    assert not (home / ".camoufox").exists()


def test_fetch_prepares_profile_directory(monkeypatch):
    calls = []
    monkeypatch.setattr(multiversion, "install_versioned", lambda *args, **kwargs: None)
    monkeypatch.setattr(pkgman, "ensure_browser_profile_dir", lambda: calls.append(True))
    fetcher = object.__new__(pkgman.CamoufoxFetcher)

    fetcher.install()

    assert calls == [True]


def test_launch_preflight_runs_before_fingerprint_generation(monkeypatch):
    class PreflightReached(Exception):
        pass

    def stop_at_preflight(env):
        raise PreflightReached

    monkeypatch.setattr(utils, "ensure_browser_profile_dir", stop_at_preflight)
    with pytest.raises(PreflightReached):
        utils.launch_options(env={"HOME": "/read-only"})
