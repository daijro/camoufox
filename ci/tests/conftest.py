import importlib.util
import sys

import pytest

from ci._util import BROWSER_ROOT


@pytest.fixture(autouse=True)
def _first_attempt(monkeypatch):
    """Run every test as a first attempt, whatever job runs the suite.

    A re-run job sets GITHUB_RUN_ATTEMPT, which renames saved evidence to
    `<gate>.attemptN.json`; tests that read `<gate>.json` then fail only on
    re-runs. Tests about re-runs set the variable themselves.
    """
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)


@pytest.fixture
def load_patch_py(monkeypatch):
    """Import browser/scripts/patch.py as `make` runs it with the given options.

    Its module level parses argv, so it must see a real invocation, not pytest's.
    """

    def load(*options):
        monkeypatch.setattr(sys, "argv", ["patch.py", "1.0", "r1", *options])
        monkeypatch.syspath_prepend(str(BROWSER_ROOT / "scripts"))
        spec = importlib.util.spec_from_file_location("patch_py", BROWSER_ROOT / "scripts" / "patch.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load
