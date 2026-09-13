"""Shared plumbing for the pipeline: paths, subprocess, JSON, hashing, logging.

Deliberately dependency-free (stdlib only) so the early steps can run on a bare
runner before anything is installed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, NoReturn, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_DIR = REPO_ROOT / "ci"
SKIPLIST_PATH = CI_DIR / "skiplist.yml"

# Where a run scatters its intermediate state. Overridable so a local operator
# can keep several runs side by side, and so a sharded CI job can hand each
# shard its own directory.
WORK_DIR = Path(os.environ.get("CI_WORK_DIR", os.environ.get("HARNESS_WORK_DIR", REPO_ROOT / ".ci-work")))
RESULTS_DIR = Path(os.environ.get("CI_RESULTS_DIR", os.environ.get("HARNESS_EVIDENCE_DIR", WORK_DIR / "results")))

# Kept under the old name so harness code and existing call sites read the same.
EVIDENCE_DIR = RESULTS_DIR

# Salt for the opaque test identifiers written into the baseline. Sundial's
# vector names are private (see TRIBAL-KNOWLEDGE.md, "Never publish a vector
# name"), so the baseline stores HMACs instead. The default salt is a repo
# constant on purpose: it makes the baseline reproducible for anyone who can
# already run sundial, and useless to anyone who cannot, because inverting it
# requires the private vector list. Override only if you want the baseline
# unreadable even to someone holding that list.
DEFAULT_ID_SALT = "camoufox-harness/v1"


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------

_START = time.monotonic()


def log(msg: str, *, level: str = "INFO") -> None:
    # stderr, so a `--json` stdout stays machine-readable and every CLI here
    # composes with a pipe. Actions shows both streams either way.
    elapsed = time.monotonic() - _START
    print(f"[{elapsed:7.1f}s] {level:<5} {msg}", file=sys.stderr, flush=True)


def die(msg: str, code: int = 1) -> NoReturn:
    log(msg, level="FATAL")
    sys.exit(code)


def group(title: str) -> None:
    """Open a collapsible section in the Actions log (a no-op elsewhere)."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::group::{title}", flush=True)
    else:
        log(f"--- {title} ---")


def endgroup() -> None:
    if os.environ.get("GITHUB_ACTIONS"):
        print("::endgroup::", flush=True)


def set_output(name: str, value: str) -> None:
    """Publish a step output when running under Actions; echo otherwise."""
    log(f"output {name}={value}")
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    # Multi-line values need the heredoc form.
    with open(path, "a", encoding="utf-8") as fh:
        if "\n" in value:
            delim = f"__EOF_{hashlib.sha256(value.encode()).hexdigest()[:16]}__"
            fh.write(f"{name}<<{delim}\n{value}\n{delim}\n")
        else:
            fh.write(f"{name}={value}\n")


def summary(markdown: str) -> None:
    """Append to the Actions job summary (the human-facing proof surface)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        print(markdown, flush=True)
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(markdown.rstrip() + "\n")


# --------------------------------------------------------------------------
# subprocess
# --------------------------------------------------------------------------


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def combined(self) -> str:
        return (self.stdout or "") + (("\n" + self.stderr) if self.stderr else "")


def run(
    cmd: Sequence[str] | str,
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
    check: bool = False,
    capture: bool = True,
    tee: bool = False,
) -> Result:
    """Run a command. Never raises on a non-zero exit unless check=True."""
    shell = isinstance(cmd, str)
    printable = cmd if shell else " ".join(shlex.quote(c) for c in cmd)
    log(f"$ {printable}" + (f"  (cwd={cwd})" if cwd else ""))

    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            shell=shell,
            timeout=timeout,
            capture_output=capture and not tee,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        err = exc.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        res = Result(124, out, err + f"\nTIMEOUT after {timeout}s")
        if check:
            die(f"command timed out: {printable}")
        return res

    res = Result(proc.returncode, proc.stdout or "", proc.stderr or "")
    if check and not res.ok:
        log(res.combined()[-4000:], level="ERROR")
        die(f"command failed ({res.code}): {printable}")
    return res


# --------------------------------------------------------------------------
# json / files
# --------------------------------------------------------------------------


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is not None:
            return default
        raise
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
        fh.write("\n")


def http_json(url: str, *, timeout: int = 30, headers: Optional[Dict[str, str]] = None) -> Any:
    """GET a URL and parse JSON. Stdlib only so this works pre-pip."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "camoufox-harness", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def http_text(url: str, *, timeout: int = 30, headers: Optional[Dict[str, str]] = None) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "camoufox-harness", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------


def opaque_id(raw: str, *, salt: Optional[str] = None) -> str:
    """Stable, non-invertible id for a private test vector.

    Used for anything sourced from sundial. The repo is public; a vector name
    in a committed baseline is a permanent leak, an HMAC is not.
    """
    key = (salt or os.environ.get("HARNESS_ID_SALT") or DEFAULT_ID_SALT).encode()
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def digest_files(paths: Iterable[Path]) -> str:
    """Order-independent digest over a set of files, for tamper detection."""
    h = hashlib.sha256()
    for path in sorted(set(Path(p) for p in paths), key=lambda p: str(p)):
        h.update(str(path.relative_to(REPO_ROOT) if path.is_absolute() else path).encode())
        h.update(b"\0")
        h.update(path.read_bytes() if path.exists() else b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


# --------------------------------------------------------------------------
# versions
# --------------------------------------------------------------------------

_VER_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def parse_version(v: str) -> Tuple[int, int, int]:
    m = _VER_RE.match(v.strip())
    if not m:
        raise ValueError(f"unparseable version: {v!r}")
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))


def major(v: str) -> int:
    return parse_version(v)[0]


def read_upstream_sh(path: Optional[Path] = None) -> Dict[str, str]:
    """Parse upstream.sh into a dict. It is shell, but strictly key=value."""
    path = path or (REPO_ROOT / "upstream.sh")
    out: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip("'\"")
    return out


def write_upstream_sh(values: Dict[str, str], path: Optional[Path] = None) -> None:
    """Rewrite upstream.sh in place, preserving key order and comments."""
    path = path or (REPO_ROOT / "upstream.sh")
    lines: List[str] = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in values:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
                continue
        lines.append(line)
    for key, val in values.items():
        if key not in seen:
            lines.append(f"{key}={val}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def bump_release(release: str) -> str:
    """beta.31 -> beta.32. Anything unrecognised gets a .1 suffix."""
    m = re.match(r"^(.*?)(\d+)$", release)
    if not m:
        return f"{release}.1"
    return f"{m.group(1)}{int(m.group(2)) + 1}"
