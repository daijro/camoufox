"""The guard against driver code coming back (ci/check_no_driver.py)."""

import pytest

from ci.check_no_driver import STUB, violation, violations


@pytest.mark.parametrize("path", [
    "python/src/camoufox/__init__.py",
    "python/pyproject.toml",
    "typescript/src/index.ts",
    "typescript/package.json",
    "pythonlib/camoufox/utils.py",
    "camoufox/fingerprints.py",
    "camoufox/fingerprints/__init__.py",
    "camoufox/data/fonts.json",
    "src/index.ts",
    "launcher.py",
    "docs/example.ts",
    "camoufox_pin/utils.py",
    "npm/launch.js",
    "npm/src/index.ts",
])
def test_driver_code_is_refused(path):
    assert violation(path)


@pytest.mark.parametrize("path", [
    "browser/scripts/gen-fonts-json.py",
    "browser/tests/build-tester/src/lib/checks/extended.ts",
    "ci/release.py",
    ".github/workflows/tests.yml",
    "pyproject.toml",
    "package.json",
    "camoufox_pin/__init__.py",
    "camoufox_pin/browser-pin.json",
    "npm/index.js",
    "npm/index.d.ts",
    "npm/cli.js",
    "npm/package.json",
    "npm/LICENSE",
    "npm/camoufox_pin/browser-pin.json",
    "camoufox/__init__.py",
    "camoufox/__main__.py",
    "camoufox/LICENSE",
    "README.md",
    "docs/FONTS.md",
])
def test_the_browser_and_the_wrapper_are_allowed(path):
    assert violation(path) is None


def test_a_camoufox_module_is_allowed_only_as_the_contract_stub():
    stub = STUB.format(module="utils")
    assert violation("camoufox/utils.py", lambda rel: stub) is None
    # The stub of another module, or one that does anything more, is launcher code.
    assert violation("camoufox/utils.py", lambda rel: STUB.format(module="webgl"))
    assert violation("camoufox/utils.py", lambda rel: stub + "PATCHED = True\n")
    assert violation("camoufox/utils.py")  # unreadable


def test_the_checked_in_wrapper_passes():
    import subprocess

    from ci._util import REPO_ROOT

    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, check=True,
                             capture_output=True, text=True).stdout.splitlines()
    assert violations(tracked) == []
