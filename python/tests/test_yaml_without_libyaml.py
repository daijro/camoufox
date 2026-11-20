"""The launcher works on a PyYAML built without libyaml, which has no CLoader or CDumper."""

import subprocess
import sys

# A fresh interpreter, so the import-time Loader choice sees the stripped yaml
SCRIPT = """
import yaml
del yaml.CLoader, yaml.CDumper
yaml.__with_libyaml__ = False
from camoufox import pkgman
from camoufox._warnings import WARNINGS_DATA
pkgman.RepoConfig.load_repos()
assert WARNINGS_DATA
"""


def test_the_launcher_loads_without_libyaml():
    proc = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
