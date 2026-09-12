#!/usr/bin/env python3
"""Prepare the Firefox source tree, retrying the steps that reach the network.

`make setup-minimal && make dir && make mozbootstrap` is the front half of every
build job. Two of those three steps download things -- the Firefox tarball, and
then the toolchains `mach bootstrap` pulls from Taskcluster -- and a download
that dies mid-stream fails the whole pull request:

    requests.exceptions.ConnectionError:
        ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))
    make: *** [Makefile:95: mozbootstrap] Error 1

That is not a defect in the change under review, and re-running it by hand is
the only thing anyone ever does about it. So do that here instead, and only for
failures that look transient: a compile error or a patch that will not apply
must still fail on the first try, because retrying those only wastes a runner.

The retry lives here rather than in the Makefile so the Makefile diff stays
clean against upstream (see CLAUDE.md) and so the auto-update harness gets the
same behaviour without duplicating it in a workflow.

Run:
    python3 -m ci.run_prepare
    python3 -m ci.run_prepare --attempts 4
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
from typing import List, Optional, Tuple

from ._util import REPO_ROOT, log

# Substrings that mark a failure as "the network went away", not "this tree is
# broken". Matched against combined stdout/stderr, case-insensitively.
#
# Deliberately narrow. Anything not listed here is treated as a real failure and
# fails on the first attempt, which is the behaviour that matters: a retry loop
# that swallows a genuine breakage turns a red build into a slow red build.
_TRANSIENT = (
    "connection reset by peer",
    "connection aborted",
    "connectionreseterror",
    "temporary failure in name resolution",
    "timed out",
    "timeout was reached",
    "remote end closed connection",
    "eof occurred in violation of protocol",
    "503 service unavailable",
    "502 bad gateway",
    "504 gateway time-out",
    "failed to establish a new connection",
    "tls handshake",
    "unexpected eof",
)

# Steps in order. `retry` says whether a transient failure is worth another go;
# `make dir` applies patches and touches no network once the tarball is present,
# so a failure there is always real.
_STEPS = (
    ("setup-minimal", True),
    ("dir", False),
    ("mozbootstrap", True),
)


def is_transient(output: str) -> bool:
    low = output.lower()
    return any(marker in low for marker in _TRANSIENT)


def _summarise(output: str, limit: int = 3) -> List[str]:
    """The lines that say what went wrong, for the log line above a retry."""
    hits = [
        line.strip()
        for line in output.splitlines()
        if is_transient(line) or re.match(r"^\s*(make|mach):.*(error|failed)", line, re.I)
    ]
    return hits[-limit:]


def _run_capturing(cmd: List[str], *, timeout: int) -> Tuple[int, str]:
    """Run a command, echoing each line as it arrives and keeping a copy.

    _util.run() can stream or capture, not both -- and this needs both. Deciding
    whether a failure is transient means reading the output, and a `make dir`
    that prints nothing for five minutes while aria2c pulls a 500MB tarball
    looks exactly like a hung job.
    """
    log("$ " + " ".join(cmd) + f"  (cwd={REPO_ROOT})")
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    lines: List[str] = []

    # The reader runs on its own thread so the timeout is real. Draining the
    # pipe on this thread would block in readline until EOF, and only *then*
    # reach proc.wait(timeout=...) -- so a step that wedged without printing
    # anything (exactly what a stalled download does) would hang forever and
    # the timeout would never fire.
    def drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        lines.append(f"\nTIMEOUT after {timeout}s\n")
        code = 124
    # Give the reader a moment to flush what the process already wrote; it is a
    # daemon thread, so a wedged pipe cannot hold the process open.
    reader.join(timeout=10)
    return code, "".join(lines)


def run_step(target: str, *, retry: bool, attempts: int, backoff: int, timeout: int) -> int:
    # At least one attempt, always. `--attempts 0` reaching the loop bound would
    # skip the step entirely and return success, which is the one answer this
    # function must never invent.
    tries = max(1, attempts) if retry else 1
    for attempt in range(1, tries + 1):
        code, output = _run_capturing(["make", target], timeout=timeout)
        if code == 0:
            return 0
        if attempt == tries:
            return code
        if not is_transient(output):
            log(f"make {target} failed and the failure does not look transient; not retrying",
                level="ERROR")
            return code
        for line in _summarise(output):
            log(f"  {line}", level="WARN")
        delay = backoff * attempt
        log(f"make {target} hit a transient network failure "
            f"(attempt {attempt}/{tries}); retrying in {delay}s", level="WARN")
        time.sleep(delay)
    raise AssertionError("run_step fell out of its loop without a verdict")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=3,
                        help="tries per network-bound step (default 3)")
    parser.add_argument("--backoff", type=int, default=20,
                        help="seconds before the first retry; grows linearly")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)

    for target, retry in _STEPS:
        log(f"make {target}")
        code = run_step(target, retry=retry, attempts=args.attempts,
                        backoff=args.backoff, timeout=args.timeout)
        if code != 0:
            log(f"make {target} failed (exit {code})", level="ERROR")
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
