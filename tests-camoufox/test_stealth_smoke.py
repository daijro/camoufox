"""
Stealth surface smoke test.

Wraps the existing `build-tester/` suite in a single pytest case so the
fingerprint/anti-detection grade is reported alongside everything else and
fails CI when it drops. The detailed score breakdown is still in the
build-tester output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_TESTER = REPO_ROOT / "build-tester"


MIN_PASS_RATIO = 0.99  # >= 99% of checks must pass; current baseline is 953/956 = 99.7%.


@pytest.mark.timeout(900)
def test_build_tester_overall_grade(camoufox_binary: str) -> None:
    """Run build-tester end-to-end and assert it stays at or above the
    99% pass-ratio baseline.

    Reading build-tester's grade letter directly is too coarse (3 misses
    out of 956 checks already drops the grade from B to C). We instead
    parse the "OVERALL: ... <passed>/<total>" line and require >= 99%.
    """
    if not BUILD_TESTER.exists():
        pytest.skip("build-tester/ not present in this checkout")
    if shutil.which("npm") is None:
        pytest.skip("npm not available")

    cmd = ["bash", str(BUILD_TESTER / "run_tests.sh"), camoufox_binary]
    proc = subprocess.run(
        cmd, cwd=BUILD_TESTER, capture_output=True, text=True, check=False
    )
    out = proc.stdout + proc.stderr

    # Strip ANSI colour codes so we can match the OVERALL line.
    import re

    plain = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out)
    m = re.search(r"OVERALL:\s+\[?[A-F]\]?\s+(\d+)/(\d+)\s+checks passed", plain)
    if not m:
        # No overall line found — build-tester crashed before reporting.
        for line in out.splitlines()[-30:]:
            print(line)
        pytest.fail(f"Could not parse build-tester output (rc={proc.returncode}).")

    passed, total = int(m.group(1)), int(m.group(2))
    ratio = passed / total
    print(f"build-tester: {passed}/{total} ({ratio*100:.2f}%)")
    assert ratio >= MIN_PASS_RATIO, (
        f"Stealth pass-ratio dropped below {MIN_PASS_RATIO*100:.0f}%: "
        f"{passed}/{total} ({ratio*100:.2f}%)"
    )
