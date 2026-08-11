"""
Tests for camoufox.addons default-addon download/caching.

Regression guard for #308: a partial/failed first download leaves an empty
addon directory behind. The old "already downloaded" check was a bare
os.path.exists(dir), so that empty dir was trusted forever and every later
launch raised InvalidAddonPath ("manifest.json is missing"), unrecoverable
short of manually deleting the cache.

Run with:
    cd pythonlib && python -m pytest tests/test_addons.py -v
"""

import os
import sys

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import addons as addons_mod  # noqa: E402
from camoufox.addons import DefaultAddons, maybe_download_addons  # noqa: E402

UBO = DefaultAddons.UBO.name


@pytest.fixture
def addons_dir(tmp_path, monkeypatch):
    # Point the addon store at a throwaway dir so no real cache is touched.
    root = tmp_path / "addons"
    monkeypatch.setattr(addons_mod, "get_addon_path", lambda name: str(root / name))
    return root


def _write_manifest(url, extract_path, name):
    os.makedirs(extract_path, exist_ok=True)
    with open(os.path.join(extract_path, "manifest.json"), "w") as f:
        f.write("{}")


def test_partial_dir_is_redownloaded(addons_dir, monkeypatch):
    # Leftover empty dir from a failed first download.
    partial = addons_dir / UBO
    partial.mkdir(parents=True)
    assert not (partial / "manifest.json").exists()

    calls = []

    def fake(url, extract_path, name):
        calls.append(name)
        _write_manifest(url, extract_path, name)

    monkeypatch.setattr(addons_mod, "download_and_extract", fake)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)

    # An empty dir must trigger a re-download, not be trusted.
    assert calls == [UBO]
    assert (partial / "manifest.json").exists()
    assert out == [str(partial)]


def test_extracted_addon_is_not_redownloaded(addons_dir, monkeypatch):
    path = addons_dir / UBO
    path.mkdir(parents=True)
    (path / "manifest.json").write_text("{}")

    def boom(*a, **k):
        raise AssertionError("must not re-download an already-extracted addon")

    monkeypatch.setattr(addons_mod, "download_and_extract", boom)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)
    assert out == [str(path)]


def test_failed_download_removes_partial_dir(addons_dir, monkeypatch):
    path = addons_dir / UBO

    def fail(url, extract_path, name):
        os.makedirs(extract_path, exist_ok=True)  # partial write, then die
        raise RuntimeError("network died mid-download")

    monkeypatch.setattr(addons_mod, "download_and_extract", fail)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)

    # The partial dir must be gone so the next run re-downloads instead of
    # trusting an addon that has no manifest.json.
    assert not path.exists()
    assert out == []
