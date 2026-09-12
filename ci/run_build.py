#!/usr/bin/env python3
"""Build gate: ./mach build for linux x86_64.

Records the compiler's verdict as evidence in its own right. A tree whose
patches all apply but which does not compile is the single most common outcome
of a Firefox bump, and it has to be a named gate rather than an implicit
precondition -- otherwise a build failure looks like "the test gates did not
run" and reads as a skip.

Run:
    python3 -m ci.run_build
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

from . import results as evidence
from ._util import EVIDENCE_DIR, REPO_ROOT, read_upstream_sh, run
from ._pytest import built_binary

# mach prints errors in a few shapes; catch the common ones for the summary.
_ERROR_RE = re.compile(
    r"^(?:.*?:\d+:\d+: (?:fatal )?error: .*|error\[E\d+\].*|.*\berror: .*)$",
    re.MULTILINE,
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=18000)
    parser.add_argument("--log", type=Path, help="also tee the build log here")
    args = parser.parse_args(argv)

    up = read_upstream_sh()
    result = evidence.GateResult(gate="build")
    result.metrics.update(version=up.get("version"), release=up.get("release"), target="linux-x86_64")

    proc = run(["make", "build"], cwd=REPO_ROOT, timeout=args.timeout, tee=True, capture=False)

    binary = built_binary()
    result.metrics["exit_code"] = proc.code
    result.metrics["binary"] = str(binary)

    if proc.code == 0 and binary.exists():
        size_mb = binary.stat().st_size / (1024 * 1024)
        result.metrics["binary_size_mb"] = round(size_mb, 1)
        result.note(f"built {binary.name} ({size_mb:.1f} MB)")
        result.finish(evidence.PASS).save(args.evidence_dir)
        return 0

    if proc.code == 0 and not binary.exists():
        result.note(
            f"mach reported success but {binary} does not exist. Treating as a failure: "
            "every later gate would otherwise silently test nothing."
        )
        result.finish(evidence.FAIL).save(args.evidence_dir)
        return 1

    errors = _ERROR_RE.findall(proc.combined())[:15]
    result.note(f"mach build exited {proc.code}")
    for line in errors:
        result.note(line.strip()[:300])
    result.metrics["error_count"] = len(errors)
    result.finish(evidence.FAIL).save(args.evidence_dir)
    return 1


if __name__ == "__main__":
    sys.exit(main())
