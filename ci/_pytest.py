"""Shared pytest plumbing for the suite runners.

Locating the built binary, running pytest against a chosen interpreter, and
reading back the JUnit XML it writes. `junit_test_id` is the one that matters
beyond this file: it produces the identity a test is known by, and the vendored
and upstream suites lay their files out differently, so two runs of the same
test must still agree on what it is called.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from ._util import REPO_ROOT, Result, read_upstream_sh, run


def source_dir(version: Optional[str] = None, release: Optional[str] = None) -> Path:
    """The generated Firefox tree, e.g. camoufox-153.0.4-beta.32/."""
    up = read_upstream_sh()
    return REPO_ROOT / f"camoufox-{version or up['version']}-{release or up['release']}"


def built_binary(version: Optional[str] = None, release: Optional[str] = None) -> Path:
    """Path to the freshly built camoufox-bin. Not guaranteed to exist."""
    override = os.environ.get("CAMOUFOX_BINARY")
    if override:
        return Path(override)
    return source_dir(version, release) / "obj-x86_64-pc-linux-gnu" / "dist" / "bin" / "camoufox-bin"


def require_binary(version: Optional[str] = None, release: Optional[str] = None) -> Path:
    path = built_binary(version, release)
    if not path.exists():
        raise FileNotFoundError(
            f"no built binary at {path}. Run `make build` first, or set CAMOUFOX_BINARY."
        )
    return path


# ---------------------------------------------------------------------------
# pytest / junit
# ---------------------------------------------------------------------------

# pytest junit escapes some characters; normalise so ids are stable across
# pytest versions and across the vendored/upstream copies of a suite.
_NORM = re.compile(r"\s+")


def junit_test_id(classname: str, name: str) -> str:
    """A stable identity for one test.

    junit's `classname` is the dotted module path, which differs between the
    vendored suite (`async.test_page`) and a fetched upstream checkout
    (`tests.async.test_page`). Trimming to the last two segments makes the two
    comparable, which is the whole point of running both.
    """
    parts = [p for p in classname.split(".") if p and p != "tests"]
    module = "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")
    return _NORM.sub(" ", f"{module}.py::{name}").strip()


def parse_junit(path: Path) -> Dict[str, str]:
    """junit XML -> {test_id: pass|fail|error|skip}."""
    if not path.exists():
        return {}
    outcomes: Dict[str, str] = {}
    tree = ET.parse(path)
    for case in tree.getroot().iter("testcase"):
        tid = junit_test_id(case.get("classname", ""), case.get("name", ""))
        if not tid:
            continue
        if case.find("error") is not None:
            outcome = "error"
        elif case.find("failure") is not None:
            outcome = "fail"
        elif case.find("skipped") is not None:
            outcome = "skip"
        else:
            outcome = "pass"
        # With --count / reruns the same id appears twice; a pass on any
        # attempt wins, matching evidence.GateResult.record().
        if outcomes.get(tid) == "pass":
            continue
        outcomes[tid] = outcome
    return outcomes


def _has_plugin(python: Path, module: str) -> bool:
    return run([str(python), "-c", f"import {module}"]).ok


def run_pytest(
    *,
    cwd: Path,
    python: Path,
    args: List[str],
    junit: Path,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 7200,
    per_test_timeout: Optional[int] = 180,
) -> Result:
    """Run pytest and write junit XML.

    `per_test_timeout` guards against a hung browser wedging the whole job, but
    it needs pytest-timeout. Passing the flag without the plugin makes pytest
    exit 4 on an unrecognised argument -- which looks exactly like "the suite
    did not run", because it did not. So the flag is only added when the plugin
    is actually importable in that interpreter.
    """
    junit.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(python), "-m", "pytest", f"--junitxml={junit}", "-p", "no:randomly"]
    if per_test_timeout and _has_plugin(python, "pytest_timeout"):
        cmd.append(f"--timeout={per_test_timeout}")
    cmd.extend(args)
    return run(cmd, cwd=cwd, env=env, timeout=timeout, tee=True, capture=False)
