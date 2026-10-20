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
import re
import threading
import time
from io import BytesIO
from pathlib import Path

import pytest

from camoufox import addons as addons_mod
from camoufox.addons import DefaultAddons, add_default_addons, maybe_download_addons
from camoufox.exceptions import CorruptedDownload

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


def test_failed_download_raises_and_removes_partial_dir(addons_dir, monkeypatch):
    path = addons_dir / UBO

    def fail(url, extract_path, name):
        os.makedirs(extract_path, exist_ok=True)  # partial write, then die
        raise RuntimeError("network died mid-download")

    monkeypatch.setattr(addons_mod, "download_and_extract", fail)

    # Launching without the addon would be a different browser than asked for.
    with pytest.raises(RuntimeError, match="network died"):
        maybe_download_addons([DefaultAddons.UBO], [])

    # The partial dir must be gone so the next run re-downloads instead of
    # trusting an addon that has no manifest.json.
    assert not path.exists()


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
    monkeypatch.setattr(addons_mod, "verify_sha256", lambda *a, **k: None)
    monkeypatch.setattr(addons_mod, "unzip", fake_unzip)

    addons_mod.download_and_extract("url", str(target), UBO)

    assert seen == [False, False]
    assert sorted(os.listdir(target)) == ["background.js", "manifest.json"]
    assert os.listdir(tmp_path) == [UBO]


def test_complete_addon_installed_meanwhile_is_kept(tmp_path, monkeypatch):
    # Another process can finish installing the addon while this one extracts.
    # Its copy may already be loading in a browser, so it must not be deleted.
    target = tmp_path / UBO
    target.mkdir()

    def fake_unzip(buffer, extract_path, desc=None, bar=True):
        _write_manifest(None, extract_path, UBO)
        _write_manifest(None, str(target), UBO)
        with open(target / "theirs.js", "w") as f:
            f.write("")

    monkeypatch.setattr(addons_mod, "webdl", lambda *a, **k: b"")
    monkeypatch.setattr(addons_mod, "verify_sha256", lambda *a, **k: None)
    monkeypatch.setattr(addons_mod, "unzip", fake_unzip)

    addons_mod.download_and_extract("url", str(target), UBO)

    assert sorted(os.listdir(target)) == ["manifest.json", "theirs.js"]
    assert os.listdir(tmp_path) == [UBO]


def test_failed_download_keeps_complete_addon(addons_dir, monkeypatch):
    # This launch's download fails after another process installed the addon.
    # That copy may already be loading in a browser, so it must not be deleted.
    path = addons_dir / UBO

    def fail(url, extract_path, name):
        _write_manifest(url, str(path), name)
        raise RuntimeError("network died mid-download")

    monkeypatch.setattr(addons_mod, "download_and_extract", fail)

    out = []
    maybe_download_addons([DefaultAddons.UBO], out)

    assert (path / "manifest.json").exists()
    assert out == [str(path)]


def test_default_addons_are_pinned_to_one_file():
    for addon in DefaultAddons:
        pin = addons_mod.PINS[addon.name]
        assert addon.value == pin["url"]
        assert f"-{pin['version']}.xpi" in pin["url"]
        assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])


def test_each_pinned_version_has_its_own_cache_dir():
    # A cache filled by another release must not stand in for this one's pin.
    pin = addons_mod.PINS[UBO]
    assert Path(addons_mod.get_addon_path(UBO)) == addons_mod.ADDONS_DIR / UBO / pin["version"]


def test_download_that_does_not_match_the_pin_is_rejected(addons_dir, monkeypatch):
    monkeypatch.setattr(addons_mod, "webdl", lambda *a, **k: BytesIO(b"not the pinned xpi"))

    with pytest.raises(CorruptedDownload):
        maybe_download_addons([DefaultAddons.UBO], [])
    assert not addons_dir.exists() or not any(addons_dir.iterdir())
