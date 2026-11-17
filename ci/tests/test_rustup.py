"""browser/scripts/patch.py: the rustup binary is resolved, not assumed at ~/.cargo/bin.

issue #1059: patch.py hardcoded ~/.cargo/bin/rustup, so a distro-packaged
rustup on PATH (/usr/bin) was never seen and `make dir` died with
"~/.cargo/bin/rustup: not found".
"""

import importlib.util
import os
import sys

import pytest

from ci._util import BROWSER_ROOT


@pytest.fixture
def patch_py(monkeypatch):
    """scripts/patch.py as make dir runs it. Its module level parses argv, so
    it sees a real invocation, not pytest's."""
    monkeypatch.setattr(sys, "argv", ["patch.py", "1.0", "r1"])
    monkeypatch.syspath_prepend(str(BROWSER_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "patch_py", BROWSER_ROOT / "scripts" / "patch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _executable(path):
    path.write_text("")
    path.chmod(0o755)


def test_find_rustup_prefers_path(tmp_path, monkeypatch, patch_py):
    rustup = tmp_path / "rustup"
    _executable(rustup)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert patch_py.find_rustup() == str(rustup)


def test_find_rustup_falls_back_to_cargo_home(tmp_path, monkeypatch, patch_py):
    """With nothing on PATH, the rustup.sh default at ~/.cargo/bin/rustup wins."""
    rustup = tmp_path / ".cargo" / "bin" / "rustup"
    rustup.parent.mkdir(parents=True)
    _executable(rustup)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    assert patch_py.find_rustup() == str(rustup)


def test_find_rustup_fails_loudly_when_absent(tmp_path, monkeypatch, patch_py):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit):
        patch_py.find_rustup()