"""ci/pgo.py: the optimized-build switches and the pinned PGO profile."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from ci import pgo
from ci._util import REPO_ROOT


def _archive(path: Path, members: dict) -> str:
    with tarfile.open(path, "w:xz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """A config file and profile dir under tmp_path; returns (cfg, write)."""
    cfg = json.loads(pgo.CONFIG_PATH.read_text())
    cfg["firefox"] = pgo.read_upstream_sh()["version"]
    path = tmp_path / "optimized-build.json"
    monkeypatch.setattr(pgo, "CONFIG_PATH", path)
    monkeypatch.setattr(pgo, "PROFILE_DIR", tmp_path / "profile")
    env_file = tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def write(**profile):
        cfg["profile"].update(profile)
        path.write_text(json.dumps(cfg))

    def exported():
        text = env_file.read_text() if env_file.exists() else ""
        return dict(line.split("=", 1) for line in text.splitlines() if line)

    return cfg, write, exported


class Args:
    def __init__(self, require):
        self.require = require


def test_the_shipped_config_names_the_tree_version_and_mozillas_rust():
    cfg = json.loads(pgo.CONFIG_PATH.read_text())
    assert cfg["firefox"] == pgo.read_upstream_sh()["version"]
    # Mozilla builds 156 with Rust 1.95.0, LLVM 22 like its bootstrapped clang.
    assert cfg["rust"] == "1.95.0"


def test_an_unpinned_profile_builds_with_lto_only(pinned):
    _, write, exported = pinned
    write(tag=None, sha256=None)
    assert pgo.cmd_fetch(Args(require=False)) == 0
    assert exported() == {"CAMOUFOX_LTO": "1"}


def test_a_release_refuses_an_unpinned_profile(pinned):
    _, write, _ = pinned
    write(tag=None, sha256=None)
    with pytest.raises(SystemExit):
        pgo.cmd_fetch(Args(require=True))


def test_a_profile_for_another_firefox_is_not_used(pinned):
    cfg, write, exported = pinned
    cfg["firefox"] = "1.0"
    write(tag="pgo-1.0-r1", sha256="0" * 64)
    assert pgo.cmd_fetch(Args(require=False)) == 0
    assert "CAMOUFOX_PGO_PROFILE" not in exported()
    with pytest.raises(SystemExit):
        pgo.cmd_fetch(Args(require=True))


def test_a_pinned_profile_is_verified_and_exported(pinned, tmp_path):
    _, write, exported = pinned
    (tmp_path / "profile").mkdir()
    digest = _archive(tmp_path / "profile" / "pgo-profile.tar.xz",
                      {"merged.profdata": b"x" * 64, "en-US.log": b"jar"})
    write(tag="pgo-test-r1", sha256=digest, asset="pgo-profile.tar.xz")
    assert pgo.cmd_fetch(Args(require=True)) == 0
    env = exported()
    assert env["CAMOUFOX_LTO"] == "1"
    assert Path(env["CAMOUFOX_PGO_PROFILE"]).read_bytes() == b"x" * 64
    assert Path(env["CAMOUFOX_PGO_JARLOG"]).name == "en-US.log"


def test_an_archive_with_unexpected_members_is_refused(pinned, tmp_path):
    _, write, _ = pinned
    (tmp_path / "profile").mkdir()
    digest = _archive(tmp_path / "profile" / "pgo-profile.tar.xz",
                      {"merged.profdata": b"x", "../escape": b"y"})
    write(tag="pgo-test-r1", sha256=digest, asset="pgo-profile.tar.xz")
    with pytest.raises(SystemExit):
        pgo.cmd_fetch(Args(require=True))


def _mozconfig_options(env, *, simd=False):
    script = (
        "ac_add_options(){ echo \"$*\"; }; mk_add_options(){ :; }; "
        f". {REPO_ROOT / 'browser' / 'assets' / 'base.mozconfig'}"
    )
    out = subprocess.run(["bash", "-c", script], env={"PATH": "/usr/bin:/bin", **env},
                         capture_output=True, text=True, check=True).stdout
    words = ("simd",) if simd else ("lto", "profile", "jarlog")
    return [line for line in out.splitlines() if any(w in line for w in words)]


def test_a_local_build_is_not_optimized():
    assert _mozconfig_options({}) == []


def test_ci_builds_link_with_cross_language_lto_and_the_profile():
    assert _mozconfig_options({"CAMOUFOX_LTO": "1"}) == ["--enable-lto=cross"]
    assert _mozconfig_options({"CAMOUFOX_LTO": "1", "CAMOUFOX_PGO_PROFILE": "/p/merged.profdata"}) == [
        "--enable-lto=cross",
        "--enable-profile-use=cross",
        "--with-pgo-profile-path=/p/merged.profdata",
    ]


def test_the_training_build_is_instrumented_and_not_lto():
    assert _mozconfig_options({"CAMOUFOX_PGO_GENERATE": "1", "CAMOUFOX_LTO": "1"}) == [
        "--enable-profile-generate=cross",
    ]


def test_both_stages_build_rust_with_simd_like_stock():
    """Stock 152.0.4's about:buildconfig has --enable-rust-simd; the profile
    only matches the final build if the training build had it too."""
    assert _mozconfig_options({}, simd=True) == []
    for env in ({"CAMOUFOX_LTO": "1"}, {"CAMOUFOX_PGO_GENERATE": "1"}):
        assert _mozconfig_options(env, simd=True) == ["--enable-rust-simd"], env


def test_llvm_versions_are_read_from_both_tools():
    assert pgo.llvm_major("rustc 1.90.0\nLLVM version: 20.1.8\n", r"LLVM version: (\d+)") == 20
    assert pgo.llvm_major("clang version 20.1.8 (taskcluster-x)\n", r"clang version (\d+)") == 20
