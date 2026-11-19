"""The launcher works on a PyYAML built without libyaml, which has no CLoader or CDumper."""

import subprocess
import sys

# A fresh interpreter, so the import-time Loader choice sees the stripped yaml
SCRIPT = """
import yaml
del yaml.CLoader, yaml.CDumper
yaml.__with_libyaml__ = False
from camoufox import geolocation, pkgman
assert (pkgman.Loader, pkgman.Dumper) == (yaml.Loader, yaml.Dumper)
geolocation._load_geoip_repos()
yaml.dump({"name": "x"}, Dumper=pkgman.Dumper)
"""


def test_the_launcher_loads_without_libyaml():
    proc = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
