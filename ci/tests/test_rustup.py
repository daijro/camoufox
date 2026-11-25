"""The build finds rustup wherever it is installed, and install-deps.sh installs it.

issue #1059: patch.py hardcoded ~/.cargo/bin/rustup, so a distro-packaged
rustup on PATH (/usr/bin) was never seen and `make dir` died with
"~/.cargo/bin/rustup: not found". install-deps.sh skipped rustup whenever
rustc and cargo were present, so a distro Rust without rustup stayed broken.
"""

import shutil
import subprocess

import pytest

from ci._util import BROWSER_ROOT


@pytest.fixture
def patch_py(load_patch_py):
    return load_patch_py()


def _executable(path, body=""):
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def empty_path(tmp_path, monkeypatch):
    """A home and PATH with no rustup on them."""
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))


def test_find_rustup_prefers_path(tmp_path, monkeypatch, patch_py):
    rustup = tmp_path / "rustup"
    _executable(rustup)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert patch_py.find_rustup() == str(rustup)


def test_find_rustup_falls_back_to_cargo_home(tmp_path, empty_path, patch_py):
    """With nothing on PATH, the rustup.sh default at ~/.cargo/bin/rustup wins."""
    rustup = tmp_path / ".cargo" / "bin" / "rustup"
    rustup.parent.mkdir(parents=True)
    _executable(rustup)
    assert patch_py.find_rustup() == str(rustup)


def test_find_rustup_fails_loudly_when_absent(empty_path, patch_py):
    with pytest.raises(SystemExit):
        patch_py.find_rustup()


def test_find_rustup_rejects_a_file_it_cannot_run(tmp_path, empty_path, patch_py):
    rustup = tmp_path / ".cargo" / "bin" / "rustup"
    rustup.parent.mkdir(parents=True)
    rustup.write_text("")
    with pytest.raises(SystemExit):
        patch_py.find_rustup()


def test_install_rust_runs_the_rustup_on_path(tmp_path, monkeypatch, patch_py):
    """The directory has a space in it, so the path must reach the shell quoted."""
    bin_dir = tmp_path / "distro bin"
    bin_dir.mkdir()
    _executable(bin_dir / "rustup", '#!/bin/sh\necho "$@" > "$0.args"\n')
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(bin_dir))
    patch_py.install_rust("1.95.0", "linux")
    assert (bin_dir / "rustup.args").read_text().startswith("toolchain install 1.95.0 ")


def test_install_deps_installs_rustup_beside_a_distro_rust(tmp_path):
    """rustc and cargo on PATH without rustup still get rustup installed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("sh", "cat", "mkdir", "chmod"):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    for tool in ("rustc", "cargo"):
        _executable(bin_dir / tool, "#!/bin/sh\necho 1.0\n")
    # Stands in for sh.rustup.rs: the installer it prints adds ~/.cargo/bin/rustup.
    _executable(bin_dir / "curl", """#!/bin/sh
cat <<'INSTALLER'
mkdir -p "$HOME/.cargo/bin"
printf '#!/bin/sh\\necho rustup 1.0\\n' > "$HOME/.cargo/bin/rustup"
chmod +x "$HOME/.cargo/bin/rustup"
echo 'PATH="$HOME/.cargo/bin:$PATH"' > "$HOME/.cargo/env"
INSTALLER
""")
    # Define the script's functions without running main, which installs packages.
    script = (BROWSER_ROOT / "scripts" / "install-deps.sh").read_text()
    assert script.endswith('\nmain "$@"\n')
    script = script.removesuffix('main "$@"\n')
    subprocess.run(
        [shutil.which("bash"), "-c", script + "\ninstall_rust\n"],
        env={"HOME": str(tmp_path), "PATH": str(bin_dir)},
        check=True,
    )
    assert (tmp_path / ".cargo" / "bin" / "rustup").is_file()
