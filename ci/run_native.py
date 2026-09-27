#!/usr/bin/env python3
"""Camoufox's own suite: leaks, context-vs-browser semantics, and settled decisions.

Everything the Playwright suites cannot ask about. Split in two so the cheap
half gives fast feedback:

  --subset rules     no browser needed. Asserts the decisions in
                     ci/tribal-rules.yml are still in force -- runs in seconds
                     in the static job and fails a pull request before anyone
                     waits 40 minutes for a build.

  --subset browser   needs a built binary. Launches browsers, kills them, and
                     proves nothing was left behind; checks that a context and a
                     browser mean what the project says they mean.

Run:
    python3 -m ci.run_native --subset rules
    python3 -m ci.run_native --subset browser --binary path/to/camoufox-bin
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import results
from ._pytest import parse_junit, run_pytest
from ._util import REPO_ROOT, RESULTS_DIR, WORK_DIR, run

SUITE_DIR = REPO_ROOT / "native-tests"

FILES = {
    "rules": ["test_tribal_rules.py"],
    "browser": [
        "test_no_leaks.py",
        "test_contexts_vs_browsers.py",
        "test_crash_recovery.py",
    ],
    # Slow by construction: each mechanism is churned twice, at n and 4n, to
    # measure whether growth scales with the count -- ~38 minutes in one
    # process. Kept out of "browser" and run with --shard, one test per
    # runner, so a pull request waits minutes for it rather than most of an hour.
    "growth": ["test_memory_growth.py"],
}


def parse_shard(text: str) -> Tuple[int, int]:
    """'3/7' -> (3, 7), refusing anything that would silently run nothing."""
    index, _, count = text.partition("/")
    i, n = int(index), int(count)
    if not 1 <= i <= n:
        raise SystemExit(f"--shard {text}: want i/n with 1 <= i <= n")
    return i, n


def collect(files: List[str], env: Dict[str, str]) -> List[str]:
    """The node ids pytest would run for `files`, in its order."""
    proc = run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *files],
        cwd=SUITE_DIR, env=env, timeout=300,
    )
    return [line.strip() for line in proc.stdout.splitlines() if "::" in line]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subset", choices=["rules", "browser", "growth", "all"], default="all"
    )
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--rounds", type=int, default=3, help="launch/close rounds for leak tests")
    parser.add_argument("--browsers", type=int, default=3, help="concurrent browsers to launch")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--shard", help="run every n-th collected test, e.g. 3/7")
    args = parser.parse_args(argv)

    name = "native" if args.subset == "all" else f"native_{args.subset}"
    shard = parse_shard(args.shard) if args.shard else None
    if shard:
        # summarize.py folds <name>-<i>of<n> back into <name>.
        name = f"{name}-{shard[0]}of{shard[1]}"
    result = results.GateResult(gate=name)
    result.metrics["subset"] = args.subset

    files = (
        [f for group in FILES.values() for f in group]
        if args.subset == "all"
        else FILES[args.subset]
    )

    env = {
        # native-tests/conftest.py puts pythonlib on sys.path itself; this is
        # for the browser half, which needs a binary to point at.
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(REPO_ROOT / "pythonlib"), os.environ.get("PYTHONPATH", "")])
        ),
    }
    if args.subset != "rules":
        binary = args.binary
        if binary is None:
            from ._pytest import built_binary

            binary = built_binary()
        if not binary.exists():
            result.note(
                f"no built binary at {binary}. The browser half of this suite cannot run, "
                "and a suite that did not run has not passed."
            )
            result.finish(results.ERROR).save(args.results_dir)
            return 1
        env["CAMOUFOX_EXECUTABLE_PATH"] = str(binary.resolve())
        result.metrics["binary"] = str(binary)

    if shard:
        ids = collect(files, env)
        if not ids:
            result.note("collected no tests; the suite did not run")
            result.finish(results.ERROR).save(args.results_dir)
            return 1
        files = ids[shard[0] - 1 :: shard[1]]
        result.metrics["shard"] = f"{shard[0]}/{shard[1]}"
        if not files:
            result.note(f"shard {shard[0]}/{shard[1]} has no tests of the {len(ids)} collected")
            result.finish(results.PASS).save(args.results_dir)
            return 0

    junit = WORK_DIR / f"junit-{name}.xml"
    proc = run_pytest(
        cwd=SUITE_DIR,
        python=Path(sys.executable),
        args=[
            *files,
            "--rounds", str(args.rounds),
            "--browsers", str(args.browsers),
            # This suite is run from several places against several binaries;
            # a .pytest_cache left in the tree would make --last-failed and
            # friends carry state between them.
            "-p", "no:cacheprovider",
        ],
        junit=junit,
        env=env,
        timeout=args.timeout,
        # A leak round launches several browsers and waits for them to settle;
        # the default 180s per test is too tight for that.
        per_test_timeout=900,
    )

    outcomes = parse_junit(junit)
    if not outcomes:
        result.note(f"pytest exited {proc.code} with no junit output; the suite did not run")
        result.finish(results.ERROR).save(args.results_dir)
        return 1

    for tid, outcome in outcomes.items():
        result.record(tid, outcome)

    tally = result.tally()
    result.artifacts.append(junit.name)
    result.metrics["exit_code"] = proc.code
    result.note(
        f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed, "
        f"{tally.get('error', 0)} errored, {tally.get('skip', 0)} skipped "
        f"({tally.get('total', 0)} collected)"
    )

    failing = tally.get("fail", 0) + tally.get("error", 0)
    status = results.PASS if failing == 0 else results.FAIL
    result.finish(status).save(args.results_dir)
    return 0 if status == results.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
