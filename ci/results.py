"""The evidence bundle: the only thing allowed to decide whether a run is green.

Every gate writes one JSON file here and nothing else. `verify.py` reads those
files and the baseline, and computes the verdict. No gate reports its own
verdict to the pull request, and the repair agent never writes into this
directory -- so "the agent said it worked" is structurally not a thing that can
happen.

Two properties do the real work:

  * A required gate with no evidence file is a FAILURE, not a skip. Deleting or
    short-circuiting a gate cannot make a run pass.
  * Every record is stamped with the current run id. A stale file left over
    from an earlier run does not satisfy a gate.
"""

from __future__ import annotations

import os
import platform
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._util import EVIDENCE_DIR, log, read_json, write_json

SCHEMA = 1

PASS = "pass"
FAIL = "fail"
ERROR = "error"
SKIP = "skip"


def run_id() -> str:
    """Identity of the current run, so stale evidence cannot be reused."""
    return (
        os.environ.get("HARNESS_RUN_ID")
        or os.environ.get("GITHUB_RUN_ID", "")
        + ("-" + os.environ.get("GITHUB_RUN_ATTEMPT", "") if os.environ.get("GITHUB_RUN_ATTEMPT") else "")
        or f"local-{socket.gethostname()}-{os.getpid()}"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class GateResult:
    """One gate's findings.

    `tests` is the part that matters for regression detection: a mapping of
    stable test identity -> outcome. Identities, not counts, are what the
    baseline compares, because a suite whose totals match can still have
    swapped which tests pass.
    """

    gate: str
    status: str = ERROR
    started: str = field(default_factory=_now)
    finished: Optional[str] = None
    tests: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    run_id: str = field(default_factory=run_id)
    schema: int = SCHEMA
    host: str = field(default_factory=lambda: f"{platform.system()}-{platform.machine()}")

    def note(self, msg: str) -> None:
        log(f"[{self.gate}] {msg}")
        self.notes.append(msg)

    def record(self, test_id: str, outcome: str) -> None:
        # A test that ran twice (retries) keeps its best outcome: a test that
        # passes on any attempt is not a regression.
        prior = self.tests.get(test_id)
        if prior == PASS:
            return
        self.tests[test_id] = outcome

    def tally(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for outcome in self.tests.values():
            out[outcome] = out.get(outcome, 0) + 1
        out["total"] = len(self.tests)
        return out

    def finish(self, status: str) -> "GateResult":
        self.status = status
        self.finished = _now()
        if self.tests:
            self.metrics.setdefault("tally", self.tally())
        return self

    def save(self, directory: Optional[Path] = None) -> Path:
        directory = directory or EVIDENCE_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.gate}.json"
        write_json(path, asdict(self))
        log(f"[{self.gate}] evidence -> {path} ({self.status}, {len(self.tests)} tests)")
        return path


def load(gate: str, directory: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    directory = directory or EVIDENCE_DIR
    path = directory / f"{gate}.json"
    if not path.exists():
        return None
    return read_json(path)


def load_all(directory: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    directory = directory or EVIDENCE_DIR
    if not directory.exists():
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = read_json(path, default={})
        if isinstance(data, dict) and data.get("gate"):
            out[data["gate"]] = data
    return out
