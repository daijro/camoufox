#!/usr/bin/env python3
"""
Fail if synthesized input is dispatched anywhere but MouseDispatch.js.

Four deadlocks shipped from call sites doing their own coordinate guard; see
docs/input-dispatch.md and input-through-one-chokepoint in ci/tribal-rules.yml.

    python3 scripts/check-input-dispatch.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOT = ROOT / "additions" / "juggler"
CHOKEPOINT = "additions/juggler/input/MouseDispatch.js"
# Paths here are relative to browser/; the design note lives at the repo root.
DOC = "../docs/input-dispatch.md"

# Both exemptions are in the content process, where no ack is awaited: PageAgent
# drags with coordinates already content-relative, and FrameTree produces the ack.
CONTENT_DRAG = "additions/juggler/content/PageAgent.js"
CONTENT_ACK_SOURCE = "additions/juggler/content/FrameTree.js"

# (regex, what the code is doing, files exempt in addition to the chokepoint)
RULES = [
    (r"\bjugglerSendMouseEvent\s*\(", "dispatches a synthesized mouse event", {CONTENT_DRAG}),
    (r"\bsendWheelEvent\s*\(", "dispatches a synthesized wheel event", set()),
    (r"\bjugglerEventId\b", "waits for a renderer ack", {CONTENT_ACK_SOURCE}),
    (r"\bboundingBox\s*\.\s*(?:left|top)\b", "does browser-relative coordinate arithmetic", set()),
]

REMEDY = (
    f"Route it through MouseDispatch ({CHOKEPOINT}): sendAcked() to dispatch and\n"
    f"    wait under a deadline, isInViewport() for the bounds predicate,\n"
    f"    toAbsolute() for the conversion. See {DOC}."
)


def main() -> int:
    if not (ROOT / CHOKEPOINT).is_file():
        print(f"FAIL: the chokepoint {CHOKEPOINT} is missing.")
        print("      If it moved, update CHOKEPOINT in this script and in " + DOC + ".")
        return 1

    compiled = [(re.compile(p), what, exempt) for p, what, exempt in RULES]
    violations = []

    for path in sorted(SCAN_ROOT.rglob("*.js")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == CHOKEPOINT or path.name.endswith(".bak"):
            continue
        for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            for pattern, what, exempt in compiled:
                if rel in exempt:
                    continue
                if pattern.search(line):
                    violations.append((rel, lineno, what, line.strip()))

    if not violations:
        scanned = sum(1 for _ in SCAN_ROOT.rglob("*.js"))
        print(f"input-dispatch: ok -- {scanned} files scanned, all synthesized input "
              f"goes through {CHOKEPOINT}")
        return 0

    print("input-dispatch: FAILED\n")
    for rel, lineno, what, line in violations:
        print(f"  {rel}:{lineno} {what} outside the chokepoint")
        print(f"    {line}")
    print(f"\n    {REMEDY}")
    print(f"\n{len(violations)} violation(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
