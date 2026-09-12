#!/usr/bin/env python3
"""Patch-guard gate: tests/patches/*.py, one standalone guard per shipped behaviour.

These are the assertions that each spoofing patch still does what it claims --
isolated evaluate, trusted events, font spoofing, mouse trajectories and so on.
They are the most direct evidence that a Firefox bump did not quietly neuter a
patch that still applies cleanly, which is the failure mode a compile check
cannot catch.

Each guard is a standalone script exiting 0 or 1. Policy allows zero failures.

Run:
    python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import results as evidence
from ._util import EVIDENCE_DIR, REPO_ROOT, log, run

GUARD_DIR = REPO_ROOT / "tests" / "patches"


def guards() -> List[Path]:
    """Every guard script. helpers.py is a library, not a guard."""
    return sorted(p for p in GUARD_DIR.glob("*.py") if p.name != "helpers.py")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=600, help="per guard")
    parser.add_argument("--only", nargs="*", help="run only these guard names")
    args = parser.parse_args(argv)

    from ._pytest import built_binary

    result = evidence.GateResult(gate="patch_guards")
    binary = args.binary or built_binary()
    if not binary.exists():
        result.note(f"no built binary at {binary}")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    env = {
        "CAMOUFOX_EXECUTABLE_PATH": str(binary),
        # The guards drive the browser through the Python package, which resolves
        # the binary from this variable rather than a packaged install.
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(REPO_ROOT / "pythonlib"), os.environ.get("PYTHONPATH", "")])
        ),
    }

    selected = [g for g in guards() if not args.only or g.stem in args.only]
    if not selected:
        result.note("no guards found -- tests/patches/ is empty or the filter matched nothing")
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    failed: List[str] = []
    for guard in selected:
        proc = run([sys.executable, str(guard)], cwd=REPO_ROOT, env=env, timeout=args.timeout)
        outcome = evidence.PASS if proc.ok else evidence.FAIL
        result.record(f"patches/{guard.name}", outcome)
        if not proc.ok:
            failed.append(guard.name)
            tail = proc.combined().strip().splitlines()[-6:]
            result.note(f"{guard.name} failed ({proc.code}): " + " | ".join(t.strip() for t in tail))
        else:
            log(f"  ✓ {guard.name}")

    passed = len(selected) - len(failed)
    result.note(f"{passed}/{len(selected)} guards passed")
    status = evidence.PASS if not failed else evidence.FAIL
    result.finish(status).save(args.evidence_dir)
    return 0 if status == evidence.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
