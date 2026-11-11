"""general.cpu_identity 1 and 2: the recorded Intel and AMD tables and the code that reads them.

browser/tests/cpu-estimates explains the recording; these keep the generated
header, the C emulation and the launcher's pref values in step with it.
"""

import json
import platform
import re
import shutil
import subprocess
import sys

import pytest

from ci._util import REPO_ROOT

BROWSER = REPO_ROOT / "browser"
OPTS = BROWSER / "additions" / "gfx" / "skia" / "skia" / "src" / "opts"


def test_the_generated_tables_are_current():
    subprocess.run([sys.executable, str(BROWSER / "scripts" / "gen-cpu-estimate-tables.py"), "--check"], check=True)


def test_the_launcher_sends_the_patchs_vendor_numbers():
    header = (OPTS / "SkCpuEstimates.h").read_text()
    enum = {m[1]: int(m[2]) for m in re.finditer(r"SK_CPU_(?:VENDOR|IDENTITY)_(INTEL|AMD|ARM64) = (\d+)", header)}
    constants = json.loads((REPO_ROOT / "python" / "src" / "camoufox" / "launcher-constants.json").read_text())
    table = constants["cpuIdentityPref"]
    assert {"INTEL": table["x86/intel"], "AMD": table["x86/amd"], "ARM64": table["arm"]} == enum == {"INTEL": 1, "AMD": 2, "ARM64": 3}


@pytest.mark.skipif(
    platform.machine().lower() not in ("x86_64", "amd64") or not shutil.which("cc"),
    reason="needs an x86-64 host with a C compiler",
)
def test_the_emulation_reproduces_both_vendors_instructions():
    # Every 2^32 input: the host vendor's emulation against the native
    # instruction, and both vendors' emulation against the recorded hashes.
    subprocess.run([sys.executable, str(BROWSER / "tests" / "cpu-estimates" / "check.py")], check=True)
