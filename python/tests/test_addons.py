"""
Tests for camoufox.addons default-addon download/caching.

Regression guard for #308: a partial/failed first download leaves an empty
addon directory behind. The old "already downloaded" check was a bare
os.path.exists(dir), so that empty dir was trusted forever and every later
launch raised InvalidAddonPath ("manifest.json is missing"), unrecoverable
short of manually deleting the cache.

Run with:
    cd python && python -m pytest tests/test_addons.py -v
"""

import os
import threading
import time

import pytest

from camoufox import addons as addons_mod
from camoufox.addons import DefaultAddons, add_default_addons, maybe_download_addons

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


def test_concurrent_launches_download_once(addons_dir, monkeypatch):
    # Two launches in one process share the check-then-extract. A lock created
    # per call guarded nothing, so both saw no manifest and both downloaded.
    calls = []

    def slow(url, extract_path, name):
        calls.append(name)
        time.sleep(0.2)
        _write_manifest(url, extract_path, name)

    monkeypatch.setattr(addons_mod, "download_and_extract", slow)

    outs = [[], []]
    threads = [threading.Thread(target=add_default_addons, args=(out,)) for out in outs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls == [UBO]
    assert outs == [[str(addons_dir / UBO)]] * 2


def test_extraction_appears_complete_or_not_at_all(tmp_path, monkeypatch):
    # Another process checks for manifest.json without the lock, so the addon
    # directory must never hold a manifest while its other files are missing.
    target = tmp_path / UBO
    target.mkdir()
    seen = []

    def fake_unzip(buffer, extract_path, desc=None, bar=True):
        seen.append((target / "manifest.json").exists())
        _write_manifest(None, extract_path, UBO)
        with open(os.path.join(extract_path, "background.js"), "w") as f:
            f.write("")
        seen.append((target / "manifest.json").exists())

    monkeypatch.setattr(addons_mod, "webdl", lambda *a, **k: b"")
    monkeypatch.setattr(addons_mod, "unzip", fake_unzip)

    addons_mod.download_and_extract("url", str(target), UBO)

    assert seen == [False, False]
    assert sorted(os.listdir(target)) == ["background.js", "manifest.json"]
    assert os.listdir(tmp_path) == [UBO]
