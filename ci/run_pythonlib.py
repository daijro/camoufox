#!/usr/bin/env python3
"""pythonlib gate: the Python package's own test suite.

Cheap, browser-free, and the first thing to break when a Firefox bump changes a
version constraint or a fingerprint preset shape. Runs early so an obvious
mistake does not cost a 40-minute build.

Run:
    python3 -m ci.run_pythonlib
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import results as evidence
from ._util import EVIDENCE_DIR, REPO_ROOT, WORK_DIR
from ._pytest import parse_junit, run_pytest

PYTHONLIB = REPO_ROOT / "pythonlib"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    result = evidence.GateResult(gate="pythonlib")
    if not (PYTHONLIB / "tests").is_dir():
        result.note("pythonlib/tests does not exist")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    junit = WORK_DIR / "junit-pythonlib.xml"
    proc = run_pytest(
        cwd=PYTHONLIB, python=args.python, args=["tests/"], junit=junit, timeout=args.timeout
    )
    outcomes = parse_junit(junit)
    if not outcomes:
        result.note(f"pytest exited {proc.code} with no junit output; the suite did not run")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    for tid, outcome in outcomes.items():
        result.record(tid, outcome)

    tally = result.tally()
    result.artifacts.append(junit.name)
    result.metrics["exit_code"] = proc.code
    result.note(
        f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed, "
        f"{tally.get('error', 0)} errored ({tally.get('total', 0)} collected)"
    )
    failing = tally.get("fail", 0) + tally.get("error", 0)
    status = evidence.PASS if failing == 0 else evidence.FAIL
    result.finish(status).save(args.evidence_dir)
    return 0 if status == evidence.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
