"""
Tests for camoufox.addons: the default addons are the ones the browser bundles.

Each browser release carries uBlock Origin under addons/UBO/ beside its binary
(Contents/Resources/addons/UBO/ in a macOS app bundle), put there by
browser/scripts/fetch-ubo.py when it is packaged. The launcher loads that copy,
so the uBO a user runs is the one the release was tested with.

Run with:
    cd python && python -m pytest tests/test_addons.py -v
"""

import warnings
from pathlib import Path

from camoufox.addons import DefaultAddons, add_default_addons, get_addon_path


def _build(root: Path, *, mac: bool = False, bundled: bool = True) -> Path:
    """A build's executable, with uBO bundled where packaging puts it."""
    if mac:
        binary = root / "Camoufox.app" / "Contents" / "MacOS" / "camoufox"
        files = root / "Camoufox.app" / "Contents" / "Resources"
    else:
        binary, files = root / "camoufox-bin", root
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("")
    if bundled:
        (files / "addons" / "UBO").mkdir(parents=True)
        (files / "addons" / "UBO" / "manifest.json").write_text("{}")
    return binary


def test_the_bundled_addon_beside_the_binary_is_loaded(tmp_path):
    binary = _build(tmp_path)
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        add_default_addons(out, None, binary)
    assert out == [str(tmp_path / "addons" / "UBO")]


def test_a_mac_app_bundle_keeps_it_in_resources(tmp_path):
    binary = _build(tmp_path, mac=True)
    expected = tmp_path / "Camoufox.app" / "Contents" / "Resources" / "addons" / "UBO"
    assert get_addon_path("UBO", binary) == str(expected)
    out = []
    add_default_addons(out, None, binary)
    assert out == [str(expected)]


def test_an_excluded_addon_is_left_out_without_a_warning(tmp_path):
    binary = _build(tmp_path, bundled=False)
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        add_default_addons(out, [DefaultAddons.UBO], binary)
    assert out == []


def test_a_build_without_the_addon_launches_without_it_and_says_so(tmp_path):
    """An older release or an unpackaged build: not an error, but not silent."""
    binary = _build(tmp_path, bundled=False)
    out = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        add_default_addons(out, None, binary)
    assert out == []
    assert len(caught) == 1
    message = str(caught[0].message)
    assert str(tmp_path / "addons" / "UBO") in message
    assert "exclude_addons" in message


def test_a_partial_directory_does_not_count(tmp_path):
    """An interrupted staging leaves no manifest.json; that is not an addon."""
    binary = _build(tmp_path, bundled=False)
    (tmp_path / "addons" / "UBO").mkdir(parents=True)
    out = []
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        add_default_addons(out, None, binary)
    assert out == []
