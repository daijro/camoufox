#!/usr/bin/env python3
"""Patch-guard gates: browser/tests/playwright/patches/*.py, one standalone guard per shipped behaviour.

Whether the patches *apply* is the build's job (browser/scripts/patch.py fails it).
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

GUARD_DIR = REPO_ROOT / "browser" / "tests" / "playwright" / "patches"


GROUPS: Dict[str, Tuple[str, ...]] = {
    "spoofing": (
        "animation-timing",
        "audio-matches-stock",
        "baseline-protections",
        "context-app-version",
        "context-lists-across-processes",
        "context-os-system-font",
        "display-scale-resolution",
        "fingerprint-setter-seal",
        "fontconfig-memo-per-context",
        "ipv4-only-network",
        "locale-explicit-names",
        "media-devices-coherence",
        "spoofed-voice-speaks",
        "startup-prefs",
        "system-font-alias-stall",
        "system-ui-font-spoofing",
        "timezone-stable",
        "touchscreen-digitizer",
        "webgl-live-state",
        "webgl-renderer-pair",
        "webrtc-context-ip",
        "webrtc-port-range",
        "worker-config-reads",
    ),
    "automation": (
        "addons-install-once",
        "debug-logging-off",
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
        "occluded-window-active",
        "trusted-events",
        "visible-automation-cues",
    ),
    "parity": (
        "certificate-revocations",
        "contentaccessible-parity",
        "firefox-version-pin",
        "getter-cost-parity",
        "gfx-probes-packaged",
        "hardware-acceleration-policy",
        "popup-blocker-parity",
        "popup-window-size",
        "search-service-init",
        "stock-gpu-parity",
        "stock-parity-probes",
        "viewport-no-rdm",
        "windows-crt-math",
        "windows-exe-manifest",
        "windows-keyboard",
    ),
}


def gate_name(group: Optional[str]) -> str:
    """patch_guards for the whole set, patch_guards_<group> for one group."""
    return f"patch_guards_{group}" if group else "patch_guards"


def guards() -> List[Path]:
    """Every guard script. helpers.py is a library, not a guard."""
    return sorted(p for p in GUARD_DIR.glob("*.py") if p.name != "helpers.py")


def leftover_browsers(binary: Path) -> List[str]:
    """Processes of the browser still running after a guard, with CPU seconds.

    Guards share one runner. A browser a guard failed to close keeps its
    content processes -- and any spinning workers -- alive into every later
    guard, which then sees a slower machine than it was written for. On Linux
    those content processes run plugin-container, which sits beside the binary.
    """
    binary = binary.resolve()
    exes = {str(binary), str(binary.parent / "plugin-container")}
    ticks = os.sysconf("SC_CLK_TCK")
    found = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if os.readlink(proc / "exe") not in exes:
                continue
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        cpu = (int(fields[11]) + int(fields[12])) / ticks
        found.append(f"pid {proc.name} cpu {cpu:.1f}s")
    return found


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
            filter(None, [str(REPO_ROOT / "python" / "src"), os.environ.get("PYTHONPATH", "")])
        ),
    }

    selected = [
        g for g in guards()
        if (not args.only or g.stem in args.only)
        and (not args.group or g.stem in GROUPS[args.group])
    ]
    if not selected:
        result.note("no guards found -- browser/tests/playwright/patches/ is empty or the filter matched nothing")
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
            # The note keeps six lines; the job log gets all of it.
            log(f"  ✗ {guard.name} output:\n{proc.combined().strip()}")
        else:
            log(f"  ✓ {guard.name}")
        leftovers = leftover_browsers(binary)
        if leftovers:
            log(f"  {guard.name} left {len(leftovers)} browser processes running: {', '.join(leftovers)}",
                level="WARN")

    passed = len(selected) - len(failed)
    result.note(f"{passed}/{len(selected)} guards passed")
    status = evidence.PASS if not failed else evidence.FAIL
    result.finish(status).save(args.evidence_dir)
    return 0 if status == evidence.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
