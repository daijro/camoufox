"""pytest plugin that lets upstream's own Playwright suite drive a Camoufox build.

Loaded with `-p` against an *unmodified* checkout of playwright-python's tests,
so upstream can refactor its conftest freely without breaking us. Four jobs:

1. **Point every launch at the build under test.** Upstream's `launch_arguments`
   fixture has no way to select a binary, so launches are intercepted at the
   implementation layer instead. Hooking `_impl` rather than the fixture is what
   makes this survive upstream reshuffling its fixtures. If no binary is given
   the plugin refuses to start, because the alternative is silently testing a
   downloaded stock Firefox and reporting a meaningless pass.

2. **Choose which world `evaluate()` runs in.** `CI_WORLD` selects it:
   `isolated` (the default, and what users get) or `main`.

   Camoufox evaluates in an isolated world -- the reason the fork exists.
   Upstream's suite asserts upstream semantics: tests read globals their own
   page scripts defined and pass handles into `evaluate()`, so a number of them
   fail on "X is not defined" for a global the page really did set. That is a
   known and deliberate divergence, not a regression.

   The suite therefore runs **isolated first**, which is the configuration users
   actually ship, and `ci/run_playwright.py` re-runs only what failed with
   `CI_WORLD=main` -- counting, naming and publishing every test that needed the
   fallback. A test that passes either way is conformant; the size of the
   fallback set is the isolated-world conformance gap, and watching it move is
   the point of measuring it this way round.

   Camoufox's own isolated-world behaviour keeps separate coverage in
   `browser/tests/playwright/patches/isolated-evaluate.py`, which must go on passing regardless --
   that is the file to check if isolation itself regresses, not this suite.

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
_WORLD_ENV = "CI_WORLD"

MAIN_WORLD = "main"
ISOLATED_WORLD = "isolated"


# ---------------------------------------------------------------------------
# skiplist
# ---------------------------------------------------------------------------


def skiplist_path(path: Optional[Path] = None) -> Path:
    """Where the skiplist is read from: $CI_SKIPLIST, else next to this file."""
    if path is not None:
        return path
    # Path("") is Path("."), which exists and is a directory -- so an unset
    # CI_SKIPLIST must be treated as unset, not as a path.
    override = os.environ.get(_SKIPLIST_ENV, "").strip()
    return Path(override) if override else Path(__file__).resolve().parent / "skiplist.yml"


def load_skiplist(path: Optional[Path] = None) -> List[Dict[str, str]]:
    path = skiplist_path(path)
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
    # Node ids arrive as `...[firefox]`; matching the bare id too keeps a `test:`
    # entry copied from a failure report from being a silent no-op.
    base = nodeid.partition("[")[0]
    # pytest node ids are posix-style even on Windows.
    for entry in entries:
        if "module" in entry:
            module = str(entry["module"]).lstrip("./")
            if nodeid.startswith(module + "::") or nodeid == module:
                return str(entry["reason"])
        elif "test" in entry:
            target = str(entry["test"]).lstrip("./")
            if nodeid == target or base == target:
                return str(entry["reason"])
        elif "pattern" in entry:
            if str(entry["pattern"]) in nodeid:
                return str(entry["reason"])
    return None


# ---------------------------------------------------------------------------
# sharding
# ---------------------------------------------------------------------------


def parse_shard(raw: Optional[str]) -> Optional[Tuple[int, int]]:
    """"3/6" -> (3, 6). One-based, like every CI UI that will display it.

    Also ci/run_native.py's: this plugin is copied into the Playwright checkout
    on its own, so it cannot import ci/_util.py.
    """
    if not raw:
        return None
    try:
        index, _, total = raw.partition("/")
        shard, count = int(index), int(total)
    except ValueError:
        raise RuntimeError(f"a shard must look like '3/6', got {raw!r}") from None
    if not (1 <= shard <= count):
        raise RuntimeError(f"shard {raw!r} is out of range")
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


def selected_world() -> str:
    """Which world this process evaluates in. Isolated unless asked otherwise.

    Defaulting to isolated means the plain `pytest -p pw_camoufox_plugin`
    someone runs by hand measures the browser as it actually ships, rather than
    a mode only the conformance suite uses.
    """
    return MAIN_WORLD if os.environ.get(_WORLD_ENV, "").strip().lower() == MAIN_WORLD else ISOLATED_WORLD


def _apply_world(world: str) -> None:
    """Set (or clear) `disableWorldIsolation` in CAMOU_CONFIG for this process.

    Clearing matters as much as setting: the fallback pass and the isolated pass
    are separate pytest processes but may inherit the same CAMOU_CONFIG from the
    job environment, and a stale `disableWorldIsolation: true` would make an
    "isolated" run quietly measure the main world -- which is precisely the
    reading this whole arrangement exists to produce.
    """
    raw = os.environ.get("CAMOU_CONFIG")
    config = json.loads(raw) if raw else {}
    if world == MAIN_WORLD:
        config["disableWorldIsolation"] = True
    else:
        config.pop("disableWorldIsolation", None)
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
    config._camoufox_world = selected_world()
    _apply_world(config._camoufox_world)
    executable = os.environ.get(_EXECUTABLE_ENV)
    if not executable:
        raise RuntimeError(
            f"{_EXECUTABLE_ENV} is not set. The upstream conformance suite has no way to "
            "select a browser binary, so without it pytest would silently test a "
            "downloaded stock Firefox and report a meaningless pass."
        )
    _install_executable_path(os.path.abspath(executable))
    config._camoufox_skiplist = load_skiplist()
    # Report the file we actually read, not where this plugin happens to sit.
    # ci/suite.py copies the plugin into the fetched checkout, so those two are
    # different directories and the header used to name a path with no file at
    # the end of it -- which is worse than saying nothing when a skip is being
    # chased down.
    config._camoufox_skiplist_path = skiplist_path()
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
    world = getattr(config, "_camoufox_world", ISOLATED_WORLD)
    lines = [
        f"camoufox: binary={os.environ.get(_EXECUTABLE_ENV)}",
        f"camoufox: evaluating in the {world} world"
        + (
            " -- this is the main-world FALLBACK pass; a test passing here failed "
            "under isolation"
            if world == MAIN_WORLD
            else " (as shipped). Failures are re-run in the main world and counted "
            "as fallbacks, not hidden."
        ),
        f"camoufox: {len(getattr(config, '_camoufox_skiplist', []))} skiplist entries "
        f"from {getattr(config, '_camoufox_skiplist_path', '(not loaded)')}",
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
