"""pytest plugin that lets upstream's own Playwright suite drive a Camoufox build.

Loaded with `-p` against an *unmodified* checkout of playwright-python's tests,
so upstream can refactor its conftest freely without breaking us. Four jobs:

1. **Point every launch at the build under test.** Upstream's `launch_arguments`
   fixture has no way to select a binary, so launches are intercepted at the
   implementation layer instead. Hooking `_impl` rather than the fixture is what
   makes this survive upstream reshuffling its fixtures. If no binary is given
   the plugin refuses to start, because the alternative is silently testing a
   downloaded stock Firefox and reporting a meaningless pass.

2. **Run in the page's own world.** Camoufox evaluates in an isolated world --
   the reason the fork exists. Upstream's suite asserts upstream semantics:
   tests read globals their own page scripts defined and pass handles into
   `evaluate()`. Roughly 37 tests fail on "X is not defined" for a global the
   page really did set. Isolation is therefore off for this suite alone, so that
   what is measured is Playwright conformance rather than the isolation design.
   Camoufox's isolated-world behaviour keeps its own coverage in
   `tests/patches/isolated-evaluate.py`, which must go on passing *without* this
   flag -- that is the file to check if isolation regresses, not this suite.

3. **Apply `ci/skiplist.yml`.** Deselects, rather than xfails, the tests Camoufox
   cannot pass by design. Deselection keeps them out of the totals entirely, so
   the pass rate means something.

4. **Shard.** `CI_SHARD=i/n` keeps a deterministic slice, so a 1500-test suite
   spreads across parallel runners. Sharding by a hash of the node id rather
   than by position means a shard's contents do not shift when upstream adds a
   test in the middle of a file.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_EXECUTABLE_ENV = "CAMOUFOX_EXECUTABLE_PATH"
_SHARD_ENV = "CI_SHARD"
_SKIPLIST_ENV = "CI_SKIPLIST"


# ---------------------------------------------------------------------------
# skiplist
# ---------------------------------------------------------------------------


def load_skiplist(path: Optional[Path] = None) -> List[Dict[str, str]]:
    if path is None:
        # Path("") is Path("."), which exists and is a directory -- so an unset
        # CI_SKIPLIST must be treated as unset, not as a path.
        override = os.environ.get(_SKIPLIST_ENV, "").strip()
        path = Path(override) if override else Path(__file__).resolve().parent / "skiplist.yml"
    if not path.is_file():
        print(f"camoufox: skiplist not found at {path}; running with no skips")
        return []
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover -- environment problem
        raise RuntimeError(
            "PyYAML is missing from the interpreter running this suite, so "
            f"{path} cannot be read. Refusing to continue: without the skiplist "
            "roughly 200 tests Camoufox cannot pass by design would run and fail, "
            "which looks like a broken browser rather than a broken environment."
        ) from exc

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = []
    for entry in data.get("skip") or []:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("reason", "")).strip():
            # Mirrors ci/summarize.py, which fails the run on an unreasoned
            # entry. Ignoring it here would let one skip tests silently.
            raise RuntimeError(f"skiplist entry has no reason: {entry!r}")
        entries.append(entry)
    return entries


def skip_reason(nodeid: str, entries: List[Dict[str, str]]) -> Optional[str]:
    """The reason this node id is skipped, or None to run it."""
    # pytest node ids are posix-style even on Windows.
    for entry in entries:
        if "module" in entry:
            module = str(entry["module"]).lstrip("./")
            if nodeid.startswith(module + "::") or nodeid == module:
                return str(entry["reason"])
        elif "test" in entry:
            if nodeid == str(entry["test"]):
                return str(entry["reason"])
        elif "pattern" in entry:
            if str(entry["pattern"]) in nodeid:
                return str(entry["reason"])
    return None


# ---------------------------------------------------------------------------
# sharding
# ---------------------------------------------------------------------------


def parse_shard(raw: Optional[str]) -> Optional[Tuple[int, int]]:
    """"3/6" -> (3, 6). One-based, like every CI UI that will display it."""
    if not raw:
        return None
    try:
        index, _, total = raw.partition("/")
        shard, count = int(index), int(total)
    except ValueError:
        raise RuntimeError(f"{_SHARD_ENV} must look like '3/6', got {raw!r}") from None
    if not (1 <= shard <= count):
        raise RuntimeError(f"{_SHARD_ENV}={raw!r} is out of range")
    return shard, count


def shard_of(nodeid: str, count: int) -> int:
    """Stable one-based shard for a node id.

    Hashed rather than positional: adding a test in the middle of a file must
    not reshuffle which shard every later test lands in, or a flake starts
    looking like it moved between runners.
    """
    digest = hashlib.sha256(nodeid.encode("utf-8")).digest()
    return (int.from_bytes(digest[:8], "big") % count) + 1


# ---------------------------------------------------------------------------
# browser wiring
# ---------------------------------------------------------------------------


def _enable_main_world() -> None:
    raw = os.environ.get("CAMOU_CONFIG")
    config = json.loads(raw) if raw else {}
    config["disableWorldIsolation"] = True
    os.environ["CAMOU_CONFIG"] = json.dumps(config)


def _install_executable_path(path: str) -> None:
    from playwright._impl._browser_type import BrowserType

    for name in ("launch", "launch_persistent_context"):
        original = getattr(BrowserType, name, None)
        if original is None or getattr(original, "_camoufox_wrapped", False):
            continue

        def make(original: Any):  # noqa: ANN401
            async def wrapper(self, *args: Any, **kwargs: Any):  # noqa: ANN401
                # playwright's _impl uses camelCase; accept either spelling so a
                # rename upstream degrades to "we set it twice", not "we set
                # nothing". A test that supplies its own path keeps it.
                if not kwargs.get("executablePath") and not kwargs.get("executable_path"):
                    kwargs["executablePath"] = path
                return await original(self, *args, **kwargs)

            wrapper._camoufox_wrapped = True  # type: ignore[attr-defined]
            return wrapper

        setattr(BrowserType, name, make(original))


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------


def pytest_configure(config) -> None:  # noqa: ANN001
    _enable_main_world()
    executable = os.environ.get(_EXECUTABLE_ENV)
    if not executable:
        raise RuntimeError(
            f"{_EXECUTABLE_ENV} is not set. The upstream conformance suite has no way to "
            "select a browser binary, so without it pytest would silently test a "
            "downloaded stock Firefox and report a meaningless pass."
        )
    _install_executable_path(os.path.abspath(executable))
    config._camoufox_skiplist = load_skiplist()
    config._camoufox_shard = parse_shard(os.environ.get(_SHARD_ENV))
    config._camoufox_skipped: Dict[str, str] = {}


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ANN001
    entries = getattr(config, "_camoufox_skiplist", [])
    shard = getattr(config, "_camoufox_shard", None)
    skipped: Dict[str, str] = getattr(config, "_camoufox_skipped", {})

    keep = []
    deselected = []
    for item in items:
        reason = skip_reason(item.nodeid, entries)
        if reason:
            skipped[item.nodeid] = reason
            deselected.append(item)
            continue
        if shard and shard_of(item.nodeid, shard[1]) != shard[0]:
            deselected.append(item)
            continue
        keep.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = keep


def pytest_report_header(config) -> List[str]:  # noqa: ANN001
    shard = getattr(config, "_camoufox_shard", None)
    lines = [
        f"camoufox: binary={os.environ.get(_EXECUTABLE_ENV)}",
        "camoufox: main-world execution enabled for this suite "
        "(isolation is covered by tests/patches/isolated-evaluate.py)",
        f"camoufox: {len(getattr(config, '_camoufox_skiplist', []))} skiplist entries "
        f"from {Path(__file__).parent / 'skiplist.yml'}",
    ]
    if shard:
        lines.append(f"camoufox: shard {shard[0]} of {shard[1]}")
    return lines


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:  # noqa: ANN001
    """Say what was skipped and why, so the list stays visible rather than silent."""
    skipped: Dict[str, str] = getattr(config, "_camoufox_skipped", {})
    if not skipped:
        return
    by_reason: Dict[str, int] = {}
    for reason in skipped.values():
        by_reason[reason] = by_reason.get(reason, 0) + 1
    terminalreporter.write_sep("-", f"camoufox skiplist: {len(skipped)} test(s) deselected")
    for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        terminalreporter.write_line(f"  {count:>4}  {' '.join(reason.split())[:150]}")
