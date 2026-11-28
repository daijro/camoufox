"""End to end: the release wrapper installed over a camoucore checkout.

What a user gets from `pip install camoufox` / `npm i camoufox`, built from
this checkout: the wrapper, stamped with a browser tag as release.yml stamps
it, installed on top of camoucore the way .github/actions/driver installs a
ci/driver-ref (camoucore's scripts/install-driver.sh, then the wrapper without
deps), and checked against camoucore's contract by ci/check_wrapper.py.

Opt-in, since it installs packages and needs network: set CAMOUCORE_DIR to a
camoucore checkout. WRAPPER_VENV names the virtualenv to install into (made
if missing; default: a fresh one under pytest's tmp_path), and WRAPPER_NPM_DIR
the npm project (default: a fresh, empty one). The npm half needs `npm` and
`node` on PATH and is skipped without them.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ci import release
from ci._util import REPO_ROOT

CAMOUCORE = os.environ.get("CAMOUCORE_DIR")
pytestmark = pytest.mark.skipif(not CAMOUCORE, reason="set CAMOUCORE_DIR to a camoucore checkout")

TAG = "v999.0.0-beta.1"
WRAPPER_PATHS = ("pyproject.toml", "README.md", "camoufox", release.PIN_PACKAGE, release.NPM_DIR)


def _run(cmd, **kw):
    out = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    assert out.returncode == 0, f"{cmd} failed ({out.returncode}):\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}"
    return out


@pytest.fixture(scope="module")
def stamped(tmp_path_factory) -> Path:
    """The wrapper's tracked files, copied and stamped with TAG."""
    root = tmp_path_factory.mktemp("wrapper")
    tracked = _run(["git", "ls-files", "--", *WRAPPER_PATHS], cwd=REPO_ROOT).stdout.splitlines()
    for rel in tracked:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, root / rel)
    release.stamp_checkout(TAG, "0.0.0", "0.0.0", "daijro/camoufox", root)
    return root


@pytest.fixture(scope="module")
def venv(tmp_path_factory) -> Path:
    path = Path(os.environ.get("WRAPPER_VENV") or tmp_path_factory.mktemp("venv") / "venv")
    if not (path / "bin" / "python").exists():
        _run(["python3", "-m", "venv", path])
    return path


@pytest.fixture(scope="module")
def npm_dir(tmp_path_factory) -> Path:
    if not (shutil.which("npm") and shutil.which("node")):
        pytest.skip("npm and node are not on PATH")
    path = Path(os.environ.get("WRAPPER_NPM_DIR") or tmp_path_factory.mktemp("npm-project"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="module")
def installed(stamped, venv, npm_dir, tmp_path_factory):
    """camoucore from CAMOUCORE_DIR (both registries' packages), then the wrapper."""
    script = Path(CAMOUCORE) / "scripts" / "install-driver.sh"
    _run(["bash", script, "camoufox",
          venv, npm_dir, "geoip"])
    _run([venv / "bin" / "pip", "install", "-q", "--no-deps", "--force-reinstall", stamped])
    packs = tmp_path_factory.mktemp("packs")
    _run(["npm", "pack", "--ignore-scripts", "--pack-destination", packs], cwd=stamped / release.NPM_DIR)
    (tgz,) = packs.glob("*.tgz")
    _run(["npm", "i", "--no-audit", "--no-fund", "--prefix", npm_dir, tgz, "playwright-core@<1.63"])
    return venv, npm_dir


def _check(venv, *args, cwd):
    # Run outside the checkout: its camoufox/ would shadow the installed one.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return _run([venv / "bin" / "python", REPO_ROOT / "ci" / "check_wrapper.py",
                 "--exact-camoucore", "--pin-tag", TAG, *args], cwd=cwd, env=env)


def test_the_python_wrapper_is_camoucores_launcher(installed, tmp_path):
    venv, _ = installed
    print(_check(venv, cwd=tmp_path).stdout)
    probe = _run([venv / "bin" / "python", "-c",
                  "import json, camoufox.sync_api as a, camoucore.camoufox.sync_api as b\n"
                  "from camoucore.camoufox import browser_pin\n"
                  "print(json.dumps([a is b, str(browser_pin.pin_file()), browser_pin.load_pin().tag]))"],
                 cwd=tmp_path).stdout
    same, pin_file, tag = json.loads(probe)
    assert same
    assert Path(pin_file).parent.name == release.PIN_PACKAGE and str(venv) in pin_file
    assert tag == TAG
    for cmd in ([venv / "bin" / "camoufox", "--help"], [venv / "bin" / "python", "-m", "camoufox", "--help"]):
        assert "fetch" in _run(cmd, cwd=tmp_path).stdout


def test_the_npm_wrapper_is_camoucores_launcher(installed, tmp_path):
    venv, npm_dir = installed
    print(_check(venv, "--no-python", "--npm-dir", npm_dir, cwd=tmp_path).stdout)
    assert "fetch" in _run(["npx", "--no-install", "camoufox", "--help"], cwd=npm_dir).stdout
