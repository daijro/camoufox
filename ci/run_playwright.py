#!/usr/bin/env python3
"""Run the Playwright suite against a Camoufox build.

One suite: playwright-python's own tests, fetched fresh at the tag
`ci/versions.py` resolved for this browser, run unmodified with
`ci/skiplist.yml` applied, plus the Camoufox-specific modules `ci/suite.py`
overlays from `browser/tests/playwright/camoufox/`.

This is the conformance check -- does Camoufox still honour the automation
contract its users hold it to -- and, through the overlay, the regression check
for the behaviours that are ours alone. Shardable.

**Isolated first, main world as a counted fallback.** Each group is run up to
three times, and normally twice:

  1. isolated world -- the configuration Camoufox actually ships. `evaluate()`
     runs in its own compartment, so a test that reads a global its page script
     defined fails here by design. Upstream's own pytest-rerunfailures has
     already retried anything that failed, so what arrives at 2 is settled.
  2. those failures with isolation off. A test that passes now is recorded as a
     **main-world fallback**: it counts as a pass for the run, and is named and
     counted in the result so the size of that set is visible and comparable
     between runs. A change in it means the isolated-world conformance gap
     moved, which is a fact about the browser worth seeing.
  3. only what failed in BOTH worlds, retried once. That set is normally empty,
     so this normally costs nothing.

Running main-world-only (the previous behaviour) hid that number entirely. A
test failing in both worlds and on retry is a plain failure.

Run:
    python3 -m ci.run_playwright --binary path/to/camoufox-bin
    python3 -m ci.run_playwright --binary path/to/camoufox-bin --shard 3/6
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import results
from ._pytest import parse_junit, require_binary, run_pytest
from ._util import REPO_ROOT, RESULTS_DIR, WORK_DIR, log
from .pw_camoufox_plugin import ISOLATED_WORLD, MAIN_WORLD
from .suite import prepare
from .versions import resolve

# The suite is named path by path rather than as `tests/`, so anything left out
# is visible. Pointing at `tests/async/` alone once dropped 722 tests (31%)
# without anyone deciding to.
class Group(NamedTuple):
    """A set of paths that share one pytest process, and whether it shards."""

    targets: Tuple[str, ...]
    sharded: bool


# Each group gets its own pytest process: the sync suite's greenlets and the
# async suite's pytest-asyncio loop break each other in one process ("Runner.run()
# cannot be called from a running event loop"), which retries then hid as flakes.
# tests/common/ and test_reference_count_async.py start their own Playwright, so
# they cannot share a process with session fixtures holding a loop.
GROUPS: Tuple[Group, ...] = (
    Group(("tests/async/",), sharded=True),
    # The sync API is a greenlet wrapper over the same Juggler traffic, so much of
    # this duplicates tests/async/ at the protocol level. It is here because
    # pythonlib ships a sync API that users drive, and the wrapper has its own
    # timeout and reentrancy behaviour the async tests cannot reach.
    Group(("tests/sync/",), sharded=True),
    # Six tests. Not sharded: splitting them would hand some shard an empty
    # selection, which pytest exits 5 for. Kept because ProtocolCallback objects
    # accumulate when the browser never replies to a protocol message, and this
    # fork patches Juggler heavily, so that leak can be ours.
    Group(("tests/common/", "tests/test_reference_count_async.py"), sharded=False),
)

TARGETS: Tuple[str, ...] = tuple(t for g in GROUPS for t in g.targets)


# The isolated pass only classifies "does this pass as Camoufox ships?", so it
# bounds what a "no" can cost. Some isolation failures hang on waits with no
# Playwright timeout behind them; 90s is three times the slowest test measured in
# the main-world baseline (30.4s over 2295 tests). Hangs this cannot bound are in
# ISOLATION_HANGS.
ISOLATED_TIMEOUT = 90

# Upstream's conftest sets `reruns = 3` under $CI. Under isolation that turns
# every deterministic world difference into four attempts (138 wasted reruns in
# one shard); a real flake still passes pass 2 and is counted as a fallback.
_NO_UPSTREAM_RERUNS = {"CI": ""}


# Isolation hangs these, and no per-test timeout can bound it: pytest-timeout's
# signal lands inside the sync API's greenlet dispatcher and wedges the process
# (run 34799668707 sat for 1h50m); the thread method kills the whole group. So
# they run in the main world and count as fallbacks; they pass there, so the
# skiplist audit would reject them. Cause: route_web_socket()'s init script lands
# in the sandbox (https://github.com/daijro/camoufox/issues/775).
ISOLATION_HANGS: Tuple[str, ...] = (
    "tests/async/test_route_web_socket.py",
    "tests/sync/test_route_web_socket.py",
)


# Left out on purpose, with the reason, so "not run" is never merely implied.
EXCLUDED = {
    "tests/test_installation.py": (
        "pip-installs playwright into a scratch environment to check packaging. "
        "That exercises Playwright's own release process, not this browser."
    ),
}


def unclaimed(checkout: Path) -> List[str]:
    """Test paths upstream ships that TARGETS neither runs nor EXCLUDED names.

    Upstream is free to add a directory, and the failure mode is silence: the
    suite quietly gets narrower and the total still looks healthy. This is the
    same hole the skiplist had one level down, so it gets the same treatment --
    a new subtree fails the run until somebody decides about it.
    """
    claimed = {t.rstrip("/") for t in TARGETS} | set(EXCLUDED)
    root = checkout / "tests"
    missed: List[str] = []
    for child in sorted(root.iterdir()):
        rel = f"tests/{child.name}"
        if rel in claimed:
            continue
        if child.is_dir():
            # Only directories that actually hold tests; assets/ and golden-*/
            # are fixtures.
            if any(child.glob("test_*.py")):
                missed.append(rel + "/")
        elif child.name.startswith("test_") and child.suffix == ".py":
            missed.append(rel)
    return missed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--browser-version", help="passed through to ci.versions")
    parser.add_argument("--playwright-tag", help="pin the suite instead of resolving one")
    parser.add_argument("--shard", help="e.g. 3/6")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--name", help="result file name; defaults to playwright[-shard]")
    # Per pytest invocation, and shorter than the job's timeout-minutes so it can
    # fire before GitHub kills the runner and the uploads with it. About four
    # times the slowest healthy group (296s).
    parser.add_argument("--group-timeout", type=int, default=1200)
    parser.add_argument("--retries", type=int, default=1, help="rerun failures this many times")
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args(argv)

    suffix = f"-{args.shard.replace('/', 'of')}" if args.shard else ""
    name = args.name or f"playwright{suffix}"
    result = results.GateResult(gate=name)

    try:
        binary = args.binary or require_binary()
    except FileNotFoundError as exc:
        result.note(str(exc))
        result.finish(results.ERROR).save(args.results_dir)
        return 1

    env = {"CAMOUFOX_EXECUTABLE_PATH": str(binary.resolve())}

    versions = resolve(
        browser_version=args.browser_version, playwright_tag=args.playwright_tag
    )
    tag = versions["playwright_tag"]
    result.metrics.update(
        playwright_tag=tag,
        playwright_firefox=versions["playwright_firefox"],
        browser_version=versions["browser_version"],
    )

    manifest = prepare(tag)
    cwd = Path(manifest["checkout"])
    python = Path(manifest["python"])
    result.metrics["camoufox_tests"] = len(manifest.get("camoufox_tests", []))

    missed = unclaimed(cwd)
    if missed:
        result.note(
            f"{tag} ships test paths this runner neither runs nor excludes: "
            + ", ".join(missed)
            + ". Add them to TARGETS, or to EXCLUDED with a reason. Refusing to report a "
            "pass over a suite that quietly got narrower."
        )
        result.finish(results.ERROR).save(args.results_dir)
        return 1

    base_args = ["-p", "pw_camoufox_plugin", "--browser", "firefox"]
    if args.headful:
        base_args.append("--headed")

    # The plugin reads the skiplist from the repository, not the fetched
    # checkout, so a local edit takes effect without re-preparing.
    env["CI_SKIPLIST"] = str(REPO_ROOT / "ci" / "skiplist.yml")
    if args.shard:
        result.metrics["shard"] = args.shard

    first_shard = not args.shard or args.shard.split("/")[0] == "1"
    outcomes: Dict[str, str] = {}
    ran: List[Group] = []
    # Still failing under isolation once flakes are excluded -- the set handed
    # to the main-world pass.
    isolated_failures: List[str] = []
    # ...and the subset of those that passed with isolation off.
    fallbacks: List[str] = []
    fallback_junits: List[str] = []
    last_code = 0

    for index, group in enumerate(GROUPS):
        if not group.sharded and not first_shard:
            continue
        group_env = dict(env)
        if args.shard and group.sharded:
            group_env["CI_SHARD"] = args.shard

        # One pytest cache per group: `lastfailed` keeps entries a run did not
        # collect, so a shared cache made `--last-failed` select everything or
        # nothing instead of this group's failures.
        cache_dir = WORK_DIR / f"pytest-cache{suffix}" / str(index)
        common = [*base_args, "-o", f"cache_dir={cache_dir}"]
        targets = ", ".join(group.targets)

        # Modules isolation hangs rather than fails. Deselected from the pass
        # below, because a hang there is not bounded by anything (ISOLATION_HANGS).
        hangs = [m for m in ISOLATION_HANGS if any(m.startswith(t) for t in group.targets)]

        # --- 1. isolated world: the browser as it ships --------------------
        log(f"group {index + 1}/{len(GROUPS)}: {targets} [{ISOLATED_WORLD} world]")
        group_junit = WORK_DIR / f"junit{suffix}-{index}.xml"
        proc = run_pytest(
            cwd=cwd,
            python=python,
            args=[*common, *[f"--ignore={m}" for m in hangs], *group.targets],
            junit=group_junit,
            env={**group_env, **_NO_UPSTREAM_RERUNS, "CI_WORLD": ISOLATED_WORLD},
            timeout=args.group_timeout,
            per_test_timeout=ISOLATED_TIMEOUT,
        )
        last_code = proc.code
        part = parse_junit(group_junit)
        if not part:
            result.note(
                f"{targets} exited {proc.code} and produced no junit "
                "results. That group did not run; it is a failure, not an empty pass."
            )
            result.finish(results.ERROR).save(args.results_dir)
            return 1
        for tid, outcome in part.items():
            if outcomes.get(tid) != results.PASS:
                outcomes[tid] = outcome
        ran.append(group)

        # --- 1b. declared hangs, straight to the main world ----------------
        #
        # Above the `failing` guard so a group with no failures still runs them,
        # with its own cache so pass 2's `--last-failed` does not re-select them.
        # Whole, on the first shard only: a shard owning none of them would
        # select nothing, and pytest's exit 5 with no junit reads as "did not run".
        if hangs and first_shard:
            log(f"  declared isolation hangs [{MAIN_WORLD} world]: {', '.join(hangs)}")
            hang_cache = WORK_DIR / f"pytest-cache{suffix}" / f"{index}-hangs"
            hang_junit = WORK_DIR / f"junit{suffix}-{index}-hangs.xml"
            run_pytest(
                cwd=cwd,
                python=python,
                args=[*base_args, "-o", f"cache_dir={hang_cache}", *hangs],
                junit=hang_junit,
                # Cleared rather than omitted: ci/_util.run() layers env over
                # os.environ, so dropping the key would still inherit one.
                # parse_shard() reads empty as "no shard", the same way
                # _NO_UPSTREAM_RERUNS clears $CI.
                env={**group_env, "CI_SHARD": "", "CI_WORLD": MAIN_WORLD},
                timeout=args.group_timeout,
            )
            fallback_junits.append(hang_junit.name)
            hung = parse_junit(hang_junit)
            if not hung:
                result.note(
                    f"the declared isolation hangs ({', '.join(hangs)}) produced no junit "
                    "results, so they did not run. Treating that as a failure: a declared "
                    "hang that stops running is how coverage disappears quietly."
                )
                result.finish(results.ERROR).save(args.results_dir)
                return 1
            for tid, outcome in hung.items():
                outcomes[tid] = outcome
            # Accounted for exactly like a discovered fallback, so the published
            # isolated-world gap keeps meaning "what isolation costs us" rather
            # than "what isolation cost us, minus the part we knew about".
            isolated_failures.extend(sorted(hung))
            fallbacks.extend(sorted(t for t, o in hung.items() if o == results.PASS))

        failing = {t for t, o in part.items() if o in (results.FAIL, results.ERROR)}
        if not failing:
            # Nothing to re-run, and this guard is load-bearing rather than an
            # optimisation: pytest declines to filter when nothing it collected
            # previously failed, so a `--last-failed` pass with an empty cache
            # runs the ENTIRE group again -- in the main world, silently
            # discarding the isolated result it was meant to refine.
            continue

        # --- 2. main world: what isolation, specifically, costs -----------
        #
        # No same-world retry first: these failures are deterministic, slow
        # (a Playwright timeout each), and upstream's pytest-rerunfailures has
        # already retried them three times. Measured, that retry cost 7m50s a
        # shard and recovered nothing; the main world recovered all 46.
        isolated_failures.extend(sorted(failing))
        log(f"  fallback [{MAIN_WORLD} world]: {len(failing)} test(s) that isolation failed")
        fallback_junit = WORK_DIR / f"junit{suffix}-{index}-mainworld.xml"
        run_pytest(
            cwd=cwd,
            python=python,
            args=[*common, "--last-failed", *group.targets],
            junit=fallback_junit,
            env={**group_env, "CI_WORLD": MAIN_WORLD},
            timeout=args.group_timeout,
        )
        fallback_junits.append(fallback_junit.name)
        recovered_in_main = parse_junit(fallback_junit)
        recovered = {t for t in failing if recovered_in_main.get(t) == results.PASS}
        for tid in recovered:
            outcomes[tid] = results.PASS
        fallbacks.extend(sorted(recovered))
        failing -= recovered

        # --- 3. failed in BOTH worlds: now a retry is worth paying for -----
        #
        # Normally empty, so the retry costs nothing on a healthy run. In the
        # permissive world, so a pass means "not reproducible": flaky, not broken.
        for attempt in range(args.retries):
            if not failing:
                break
            log(f"  retry {attempt + 1} [{MAIN_WORLD} world]: {len(failing)} test(s) that failed in both")
            retry_junit = WORK_DIR / f"junit{suffix}-{index}-retry{attempt + 1}.xml"
            run_pytest(
                cwd=cwd,
                python=python,
                args=[*common, "--last-failed", *group.targets],
                junit=retry_junit,
                env={**group_env, "CI_WORLD": MAIN_WORLD},
                timeout=args.group_timeout,
            )
            retried = parse_junit(retry_junit)
            recovered = {t for t in failing if retried.get(t) == results.PASS}
            for tid in recovered:
                outcomes[tid] = results.PASS
            if recovered:
                result.note(
                    f"{len(recovered)} test(s) that failed in both worlds passed on retry "
                    "(flaky, not counted as failures)"
                )
            failing -= recovered

    result.metrics["groups"] = len(ran)

    for tid, outcome in outcomes.items():
        result.record(tid, outcome)

    # Published on purpose. These tests pass, so they are invisible in the
    # failure count -- but this is the isolated-world conformance gap, and the
    # whole reason for running isolation first is to have a number for it that
    # moves when the browser does.
    result.metrics["isolated_world_failures"] = len(isolated_failures)
    # Declared, not measured -- so say so rather than letting them sit inside
    # the fallback count looking like something the isolated pass discovered.
    result.metrics["declared_isolation_hangs"] = list(ISOLATION_HANGS)
    result.metrics["main_world_fallback_count"] = len(fallbacks)
    result.metrics["main_world_fallbacks"] = sorted(fallbacks)
    if fallbacks:
        result.note(
            f"{len(fallbacks)} test(s) failed under world isolation and passed with it off. "
            "They count as passes -- Camoufox honours the contract -- but the set is "
            "recorded so a change in it is visible: "
            + ", ".join(sorted(fallbacks)[:8])
            + (" ..." if len(fallbacks) > 8 else "")
        )
    unexplained = len(isolated_failures) - len(fallbacks)
    if unexplained:
        result.note(
            f"{unexplained} test(s) failed in BOTH worlds; those are real failures, not "
            "an isolation difference."
        )

    tally = result.tally()
    result.artifacts.extend(
        f"junit{suffix}-{i}.xml" for i in range(len(GROUPS)) if i < len(ran)
    )
    result.artifacts.extend(fallback_junits)
    result.metrics["exit_code"] = last_code
    result.note(
        f"{tally.get('pass', 0)} passed, {tally.get('fail', 0)} failed, "
        f"{tally.get('error', 0)} errored, {tally.get('skip', 0)} skipped "
        f"({tally.get('total', 0)} collected)"
    )

    still_failing = tally.get("fail", 0) + tally.get("error", 0)
    status = results.PASS if still_failing == 0 else results.FAIL
    result.finish(status).save(args.results_dir)
    # Exit non-zero so the step goes red in the UI. ci/summarize.py still owns
    # the run's verdict -- it is the only thing that knows what was required --
    # but a green step hiding a failed suite is how a broken pipeline goes
    # unnoticed for a week. Shards are separate jobs with fail-fast disabled, so
    # one going red does not cancel its siblings.
    return 0 if status == results.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
