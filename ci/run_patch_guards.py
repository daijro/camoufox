#!/usr/bin/env python3
"""Patch-guard gates: tests/patches/*.py, one standalone guard per shipped behaviour.

Whether the patches *apply* is the build's job (scripts/patch.py fails it).
These check that what they do still works in the built browser -- the most
direct evidence that a Firefox bump did not quietly neuter a patch that still
applies cleanly, which is the failure mode a compile check cannot catch.

The guards fall into three groups, each its own suite and CI job:

  spoofing    a spoofed value still reaches the page and holds together
  automation  Playwright stays invisible to the page and never deadlocks it
  parity      what a page, or the OS, can observe matches stock Firefox

Each guard is a standalone script exiting 0 or 1. Policy allows zero failures.
Every guard belongs to exactly one group (ci/tests checks this), so a new one
cannot be left out of CI.

Run:
    python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
    python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin --group automation
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import results as evidence
from ._util import EVIDENCE_DIR, REPO_ROOT, log, run

GUARD_DIR = REPO_ROOT / "tests" / "patches"


GROUPS: Dict[str, Tuple[str, ...]] = {
    "spoofing": (
        "animation-timing",
        "fingerprint-setter-seal",
        "media-devices-coherence",
        "spoofed-voice-speaks",
        "startup-prefs",
        "system-ui-font-spoofing",
        "touchscreen-digitizer",
        "worker-config-reads",
    ),
    "automation": (
        "addons-install-once",
        "force-scope-access",
        "humanize-edge-deadlock",
        "humanize-mouse-trajectory",
        "humanize-pacing",
        "input-ack-backstop",
        "isolated-evaluate",
        "main-world-eval",
        "main-world-init-script",
        "mouse-boundary-sweep",
        "near-edge-mouse-deadlock",
        "noop-mousemove-deadlock",
        "trusted-events",
        "visible-automation-cues",
    ),
    "parity": (
        "contentaccessible-parity",
        "gfx-probes-packaged",
        "hardware-acceleration-policy",
        "popup-blocker-parity",
        "search-service-init",
        "stock-parity-probes",
        "viewport-no-rdm",
        "windows-exe-manifest",
    ),
}


def gate_name(group: Optional[str]) -> str:
    """patch_guards for the whole set, patch_guards_<group> for one group."""
    return f"patch_guards_{group}" if group else "patch_guards"


def guards() -> List[Path]:
    """Every guard script. helpers.py is a library, not a guard."""
    return sorted(p for p in GUARD_DIR.glob("*.py") if p.name != "helpers.py")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=600, help="per guard")
    parser.add_argument("--only", nargs="*", help="run only these guard names")
    parser.add_argument("--group", choices=sorted(GROUPS), help="run one group (default: all)")
    args = parser.parse_args(argv)

    from ._pytest import built_binary

    result = evidence.GateResult(gate=gate_name(args.group))
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

    selected = [
        g for g in guards()
        if (not args.only or g.stem in args.only)
        and (not args.group or g.stem in GROUPS[args.group])
    ]
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
