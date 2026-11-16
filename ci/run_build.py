#!/usr/bin/env python3
"""Build gate: browser/multibuild.py for one target, as a release runs it.

Records the compiler's verdict as evidence in its own right. A tree whose
patches all apply but which does not compile is the single most common outcome
of a Firefox bump, and it has to be a named gate rather than an implicit
precondition -- otherwise a build failure looks like "the test gates did not
run" and reads as a skip.

A pull request and a release both build through here
(ci/tribal-rules.yml: one-build-entry-point), so a step only a release runs
cannot break a commit whose tests passed. The targets a pull request does not
build get `--preflight` (browser/scripts/preflight.py).

Run:
    python3 -m ci.run_build                                     # linux x86_64
    python3 -m ci.run_build --target macos --arch arm64
    python3 -m ci.run_build --target windows --arch x86_64 --preflight
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional

from . import results as evidence
from ._util import BROWSER_ROOT, EVIDENCE_DIR, WORK_DIR, log, read_upstream_sh

# mach prints errors in a few shapes; catch the common ones for the summary.
_ERROR_RE = re.compile(
    r"^(?:.*?:\d+:\d+: (?:fatal )?error: .*|error\[E\d+\].*|.*\berror: .*)$",
    re.MULTILINE,
)


def build(cmd: List[str], log_path: Path, timeout: int) -> int:
    """Run `cmd` in BROWSER_ROOT, streaming its output to the console and to
    `log_path`. Returns its exit code, or 124 when `timeout` seconds pass.

    The build runs in its own process group, and a timeout or an interrupt ends
    the whole group: mach's compilers would otherwise outlive multibuild.py and
    keep writing to dist/ after the gate recorded its result.
    """
    log(f"$ {shlex.join(cmd)}  (cwd={BROWSER_ROOT})")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    expired = threading.Event()
    with open(log_path, "w", encoding="utf-8") as fh, subprocess.Popen(
        cmd, cwd=BROWSER_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", start_new_session=True,
    ) as proc:
        def end_group() -> None:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)

        def expire() -> None:
            expired.set()
            end_group()

        timer = threading.Timer(timeout, expire)
        timer.start()
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                fh.write(line)
            code = proc.wait()
        except BaseException:
            end_group()
            raise
        finally:
            timer.cancel()
    return 124 if expired.is_set() else code


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="linux")
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DIR)
    parser.add_argument("--timeout", type=int, default=18000)
    args = parser.parse_args(argv)

    up = read_upstream_sh()
    # One preflight record per target, so the summary lists each beside `build`.
    gate = f"preflight_{args.target}_{args.arch}" if args.preflight else "build"
    result = evidence.GateResult(gate=gate)
    result.metrics.update(version=up.get("version"), release=up.get("release"),
                          target=f"{args.target}-{args.arch}")

    cmd = [sys.executable, "multibuild.py", "--target", args.target, "--arch", args.arch]
    if args.preflight:
        cmd.append("--preflight")
    log_path = WORK_DIR / f"{gate}.log"
    code = build(cmd, log_path, args.timeout)
    result.metrics["exit_code"] = code

    if code != 0:
        errors = _ERROR_RE.findall(log_path.read_text(errors="replace"))[:15]
        result.note(f"multibuild.py exited {code}")
        for line in errors:
            result.note(line.strip()[:300])
        result.metrics["error_count"] = len(errors)
        result.finish(evidence.FAIL).save(args.evidence_dir)
        return 1

    if not args.preflight:
        packages = sorted((BROWSER_ROOT / "dist").glob(f"camoufox-*-{args.target[:3]}.{args.arch}.zip"))
        if not packages:
            result.note(
                "multibuild.py reported success but browser/dist holds no package. Treating as "
                "a failure: every later gate would otherwise silently test nothing."
            )
            result.finish(evidence.FAIL).save(args.evidence_dir)
            return 1
        size_mb = packages[-1].stat().st_size / (1024 * 1024)
        result.metrics["package"] = packages[-1].name
        result.metrics["package_size_mb"] = round(size_mb, 1)
        result.note(f"built {packages[-1].name} ({size_mb:.1f} MB)")

    result.finish(evidence.PASS).save(args.evidence_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
