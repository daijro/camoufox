"""browser/scripts/patch.py --mozconfig-only (make set-target) retargets a tree and leaves its sources alone."""

import pytest

from ci._util import BROWSER_ROOT


@pytest.fixture
def patcher(tmp_path, monkeypatch, load_patch_py):
    """scripts/patch.py as `make set-target` runs it, in a browser/ that holds
    one addition and a tree where a patch has since changed that file."""
    for shared in ("scripts", "assets", "settings"):
        (tmp_path / shared).symlink_to(BROWSER_ROOT / shared)
    branding = tmp_path / "additions" / "browser" / "branding" / "camoufox"
    branding.mkdir(parents=True)
    (branding / "Assets.car").write_bytes(b"")
    (tmp_path / "additions" / "owned.cpp").write_text("as added\n")
    tree = tmp_path / "camoufox-1.0-r1"
    (tree / "browser" / "config").mkdir(parents=True)
    (tree / "owned.cpp").write_text("as patched\n")

    monkeypatch.chdir(tmp_path)
    return load_patch_py("--mozconfig-only").Patcher, tree


def test_set_target_leaves_the_patched_sources_alone(patcher):
    Patcher, tree = patcher
    Patcher("x86_64-pc-linux-gnu", "linux", "1.95.0", "/profile").camoufox_patches()
    assert (tree / "owned.cpp").read_text() == "as patched\n"
    assert not (tree / "lw").exists()


def test_set_target_replaces_the_previous_target(patcher):
    Patcher, tree = patcher
    Patcher("x86_64-pc-linux-gnu", "linux", "1.95.0", "/profile").camoufox_patches()
    Patcher("aarch64-apple-darwin", "macos", "1.95.0", "/profile").camoufox_patches()
    mozconfig = (tree / "mozconfig").read_text()
    assert mozconfig.startswith("CAMOUFOX_TARGET=aarch64-apple-darwin\n")
    assert mozconfig.count("CAMOUFOX_TARGET=") == 1
    assert (BROWSER_ROOT / "assets" / "base.mozconfig").read_text() in mozconfig
    assert mozconfig.endswith((BROWSER_ROOT / "assets" / "macos.mozconfig").read_text())
