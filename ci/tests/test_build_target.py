"""browser/scripts/patch.py: BUILD_TARGET unset defaults to the documented build.

The README and AGENTS.md build the browser on Linux with a bare `make dir`;
make build/run/edit-cfg assume obj-x86_64-pc-linux-gnu. Defaulting to
macos,arm64 configured a macOS cross-build that failed minutes later on the
missing SDK.
"""

import importlib.util
import sys

import pytest

from ci._util import BROWSER_ROOT


@pytest.fixture
def patch_py(monkeypatch):
    """scripts/patch.py imported the way ci/tests/test_set_target.py does: its
    module level parses argv, so it sees a real invocation, not pytest's."""
    monkeypatch.setattr(sys, "argv", ["patch.py", "1.0", "r1"])
    monkeypatch.syspath_prepend(str(BROWSER_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "patch_py", BROWSER_ROOT / "scripts" / "patch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unset_defaults_to_the_documented_linux_build(patch_py, monkeypatch):
    monkeypatch.delenv("BUILD_TARGET", raising=False)
    assert patch_py.extract_build_target() == ("linux", "x86_64")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("linux,x86_64", ("linux", "x86_64")),
        ("macos,arm64", ("macos", "arm64")),
        ("windows,i686", ("windows", "i686")),
    ],
)
def test_an_explicit_build_target_wins(patch_py, monkeypatch, value, expected):
    monkeypatch.setenv("BUILD_TARGET", value)
    assert patch_py.extract_build_target() == expected


@pytest.mark.parametrize("value", ["plan9,x86_64", "linux,riscv64"])
def test_an_unknown_target_or_arch_is_rejected(patch_py, monkeypatch, value):
    monkeypatch.setenv("BUILD_TARGET", value)
    with pytest.raises(AssertionError):
        patch_py.extract_build_target()
