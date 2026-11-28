"""Where the camoufox driver keeps its launcher data.

fonts.json, font-groups.json, font-bases.json, essential-fonts.json,
font-prefs.json and launcher-constants.json ship inside the launcher,
camoucore.camoufox (the `camoucore` package), whose source is
python/camoucore/src/camoucore/camoufox in
https://github.com/CamouBrowser/camoucore. This repository does not carry
them (its `camoufox` package is only the release wrapper's stubs).

* Checks (verify-fonts.py, the tests) read the INSTALLED driver: package_dir().
* Generators (gen-fonts-json.py, gen-font-groups.py) read and write a camoucore
  CHECKOUT: camoucore_package_dir(). Name it with --camoucore DIR or the
  CAMOUCORE_DIR environment variable; the default is a `camoucore` directory
  beside this repository. Their output lands through a camoucore pull request,
  and reaches this repository's CI once that driver is released and pinned in
  the root pyproject.toml / npm/package.json (or, before that, through ci/driver-ref).
"""

import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMOUCORE_ENV = "CAMOUCORE_DIR"
# The driver package inside a camoucore checkout.
DRIVER_SOURCE = Path("python") / "camoucore" / "src" / "camoucore" / "camoufox"


def package_dir() -> Path:
    """The installed driver package (CAMOUFOX_PACKAGE_DIR overrides it)."""
    override = os.environ.get("CAMOUFOX_PACKAGE_DIR")
    if override:
        return Path(override).resolve()
    # find_spec locates camoucore without importing it, so this works before
    # its own dependencies are installed. The launcher's data is in
    # camoucore/camoufox/; the `camoufox` package is the release wrapper's
    # stubs, which carry none.
    spec = importlib.util.find_spec("camoucore")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit(
            "the camoufox driver (camoucore) is not installed; install it (see "
            "ci/README.md, 'The driver') or set CAMOUFOX_PACKAGE_DIR"
        )
    return (Path(next(iter(spec.submodule_search_locations))) / "camoufox").resolve()


def _camoucore_arg() -> Optional[str]:
    """--camoucore DIR from the running script's command line, if given."""
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--camoucore" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--camoucore="):
            return arg.split("=", 1)[1]
    return None


def camoucore_root() -> Path:
    """The camoucore checkout a generator writes into (it may not exist)."""
    root = _camoucore_arg() or os.environ.get(CAMOUCORE_ENV) or REPO_ROOT.parent / "camoucore"
    return Path(root).expanduser().resolve()


def camoucore_package_dir(required: bool = True) -> Optional[Path]:
    """The driver package inside the camoucore checkout, or None when absent
    and not `required`."""
    root = camoucore_root()
    pkg = root / DRIVER_SOURCE
    if pkg.is_dir():
        return pkg
    if required:
        raise SystemExit(
            f"no camoucore checkout at {root} ({DRIVER_SOURCE} is missing). The "
            "generators write the driver's data files into camoucore "
            "(https://github.com/CamouBrowser/camoucore): clone it and pass "
            f"--camoucore DIR or set {CAMOUCORE_ENV}, then open a camoucore pull request "
            "with the result."
        )
    return None


def add_camoucore_argument(ap) -> None:
    """The --camoucore option every generator takes (read early by camoucore_root)."""
    ap.add_argument(
        "--camoucore", metavar="DIR",
        help=f"camoucore checkout to read and write the driver's data in "
             f"(default: ${CAMOUCORE_ENV}, else {REPO_ROOT.parent / 'camoucore'})",
    )
