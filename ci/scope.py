#!/usr/bin/env python3
"""Which suites a pull request has to run, from the files it changes.

Every suite used to run on every pull request, so a change to release.yml or a
README waited ~20 minutes on six Playwright shards, seven memory-growth shards
and the patch guards, none of which read either file. This module maps each
changed file to the suites that actually read it, and tests.yml runs those.

It fails closed. A file no rule below recognises selects EVERY suite, and so
does anything that can change the browser (ci.release.is_browser_source) or the
pipeline itself. Adding a rule is how a path earns a narrower run; forgetting
one costs time, never coverage. Anything that is not a pull request -- a push
to main through release.yml, the schedule, a dispatch -- runs everything.

    python3 -m ci.scope plan --base SHA        # outputs: suites, needs_browser, guard_matrix
    python3 -m ci.scope required --suites JSON --browser-changed B --has-sundial B
    python3 -m ci.scope gate                    # the merge gate; reads RESULTS etc. from env
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from ._util import REPO_ROOT, log, run, set_output

# Suite names as tests.yml schedules them. patch-guards and skiplist-audit are
# legs of one job (`patch-guards`); every other suite is its own job.
SUITES: Tuple[str, ...] = (
    "pythonlib",
    "typescript",
    "patch-guards",
    "skiplist-audit",
    "build-tester",
    "playwright",
    "native",
    "growth",
    "typescript-browser",
    "sundial",
)
ALL: FrozenSet[str] = frozenset(SUITES)

# The suites that drive a browser, and so need `build` or `fetch-browser`.
BROWSER_SUITES: FrozenSet[str] = ALL - {"pythonlib", "typescript"}

# The patch-guards job's matrix, leg by leg, and the suite each leg belongs to.
GUARD_LEGS: Tuple[Dict[str, str], ...] = (
    {"leg": "spoofing", "title": "Patch guards: spoofing"},
    {"leg": "automation", "title": "Patch guards: automation"},
    {"leg": "parity", "title": "Patch guards: stock parity"},
    {"leg": "skiplist", "title": "Skiplist audit"},
)
LEG_SUITE = {"spoofing": "patch-guards", "automation": "patch-guards",
             "parity": "patch-guards", "skiplist": "skiplist-audit"}

# What each suite writes a result under (ci/summarize.py --require).
RESULT_NAMES: Dict[str, Tuple[str, ...]] = {
    "pythonlib": ("pythonlib",),
    "typescript": ("typescript",),
    "patch-guards": ("patch_guards_spoofing", "patch_guards_automation", "patch_guards_parity"),
    "skiplist-audit": ("skiplist_audit",),
    "build-tester": ("build_tester",),
    "playwright": ("playwright",),
    "native": ("native_browser",),
    "growth": ("native_growth",),
    "typescript-browser": ("typescript_browser",),
    "sundial": ("sundial",),
}

# Every pythonlib consumer. The upstream Playwright suite and the skiplist audit
# are not among them: they drive the binary through playwright-python with
# ci/pw_camoufox_plugin.py, and neither they nor tests/camoufox/ import camoufox.
PYTHONLIB_READERS = frozenset({
    "pythonlib", "typescript", "patch-guards", "build-tester", "native", "growth",
    "sundial", "typescript-browser",
})

# (glob, suites). The first match wins, so the specific rules sit above the
# general ones. `*` matches across `/` here (fnmatch), so `docs/*` is the whole tree.
RULES: Tuple[Tuple[str, FrozenSet[str]], ...] = (
    # The pipeline itself, and the modules every suite runner shares.
    (".github/workflows/tests.yml", ALL),
    (".github/actions/*", ALL),
    ("ci/__init__.py", ALL),
    ("ci/_util.py", ALL),
    ("ci/_pytest.py", ALL),
    ("ci/results.py", ALL),
    ("ci/summarize.py", ALL),
    ("ci/requirements.txt", ALL),
    ("ci/versions.py", ALL),
    ("ci/release.py", ALL),
    ("ci/browser_inputs.py", ALL),
    ("ci/scope.py", ALL),
    # Read only by the static job, which always runs.
    (".github/workflows/release.yml", frozenset()),
    ("ci/tests/*", frozenset()),
    ("ci/tribal-rules.yml", frozenset()),
    # Libraries.
    ("pythonlib/*", PYTHONLIB_READERS),
    ("typescript/*", frozenset({"typescript", "typescript-browser"})),
    # One suite's inputs, and its runner.
    ("ci/run_pythonlib.py", frozenset({"pythonlib"})),
    ("ci/run_typescript.py", frozenset({"typescript", "typescript-browser"})),
    ("tests/camoufox/*", frozenset({"playwright", "skiplist-audit"})),
    ("ci/skiplist.yml", frozenset({"playwright", "skiplist-audit"})),
    ("ci/pw_camoufox_plugin.py", frozenset({"playwright", "skiplist-audit"})),
    ("ci/suite.py", frozenset({"playwright", "skiplist-audit"})),
    ("ci/run_playwright.py", frozenset({"playwright"})),
    ("ci/run_skiplist_audit.py", frozenset({"skiplist-audit"})),
    ("tests/patches/*", frozenset({"patch-guards"})),
    ("ci/run_patch_guards.py", frozenset({"patch-guards"})),
    ("native-tests/*", frozenset({"native", "growth"})),
    ("ci/run_native.py", frozenset({"native", "growth"})),
    ("build-tester/*", frozenset({"build-tester"})),
    ("ci/run_build_tester.py", frozenset({"build-tester"})),
    ("ci/build-tester.yml", frozenset({"build-tester"})),
    ("ci/run_sundial.py", frozenset({"sundial"})),
    ("ci/sundial.yml", frozenset({"sundial"})),
    # Prose. Read by nothing that runs.
    ("docs/*", frozenset()),
    ("*.md", frozenset()),
    ("LICENSE", frozenset()),
)


def is_browser_source(path: str) -> bool:
    from .release import is_browser_source as browser  # the digest's own definition

    return browser(path)


def classify(path: str) -> Tuple[FrozenSet[str], str]:
    """The suites one changed file needs, and why."""
    if is_browser_source(path):
        return ALL, "browser source"
    for pattern, suites in RULES:
        if fnmatch.fnmatchcase(path, pattern):
            return suites, f"matches {pattern}"
    return ALL, "no rule covers it"


def select(changed: Iterable[str]) -> Tuple[FrozenSet[str], List[Tuple[str, FrozenSet[str], str]]]:
    """The union of every changed file's suites, with the per-file reasons."""
    selected: set = set()
    reasons = []
    for path in changed:
        suites, why = classify(path)
        selected |= suites
        reasons.append((path, suites, why))
    return frozenset(selected), reasons


def ordered(suites: Iterable[str]) -> List[str]:
    wanted = set(suites)
    return [s for s in SUITES if s in wanted]


def guard_matrix(suites: Iterable[str]) -> List[Dict[str, str]]:
    wanted = set(suites)
    return [dict(leg) for leg in GUARD_LEGS if LEG_SUITE[leg["leg"]] in wanted]


def required(suites: Iterable[str], browser_changed: bool, has_sundial: bool) -> List[str]:
    """The result names summarize must see, for the suites this run scheduled.

    native_rules comes from the static job, which runs on every pull request.
    `build` writes a result only when the browser was built rather than fetched.
    sundial needs a credential, which a fork pull request does not have.
    """
    wanted = set(suites)
    names = ["native_rules"]
    for suite in SUITES:
        if suite not in wanted or (suite == "sundial" and not has_sundial):
            continue
        names.extend(RESULT_NAMES[suite])
    if browser_changed and wanted & BROWSER_SUITES:
        names.append("build")
    return names


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

# tests.yml job -> the suites it runs. A job may be skipped only when none of
# them was selected.
JOB_SUITES: Dict[str, FrozenSet[str]] = {
    "pythonlib": frozenset({"pythonlib"}),
    "typescript": frozenset({"typescript"}),
    "patch-guards": frozenset({"patch-guards", "skiplist-audit"}),
    "build-tester": frozenset({"build-tester"}),
    "playwright": frozenset({"playwright"}),
    "native": frozenset({"native"}),
    "growth": frozenset({"growth"}),
    "typescript-browser": frozenset({"typescript-browser"}),
    "sundial": frozenset({"sundial"}),
}


def may_skip(suites: Iterable[str], browser_changed: bool, has_sundial: bool) -> Dict[str, bool]:
    """Which gate needs may be `skipped`, and only for these reasons."""
    wanted = set(suites)
    needs_browser = bool(wanted & BROWSER_SUITES)
    allowed = {job: not (s & wanted) for job, s in JOB_SUITES.items()}
    allowed["sundial"] = allowed["sundial"] or not has_sundial
    allowed["build"] = not (needs_browser and browser_changed)
    allowed["fetch-browser"] = not needs_browser or browser_changed
    return allowed


def gate(results: Dict[str, str], suites: Sequence[str], browser_changed: bool,
         has_sundial: bool) -> List[str]:
    """Every problem that makes this run unmergeable; empty means mergeable.

    Anything not `success` fails, `skipped` included, unless may_skip() allows
    it: a suite that was selected and did not run has not passed.
    """
    allowed = may_skip(suites, browser_changed, has_sundial)
    problems = []
    for name, result in sorted(results.items()):
        if result == "success":
            continue
        if result == "skipped" and allowed.get(name):
            print(f"  - {name}: skipped (not applicable to this run)")
            continue
        problems.append(f"{name}: {result}")
    return problems


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _changed(base: str) -> List[str]:
    out = run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=REPO_ROOT, check=True).stdout
    return [line for line in out.splitlines() if line]


def cmd_plan(args: argparse.Namespace) -> int:
    if args.all:
        suites, reasons = ALL, []
        log(f"not a pull request ({args.all}): every suite runs")
    else:
        changed = _changed(args.base)
        suites, reasons = select(changed)
        for path, picked, why in reasons:
            label = "every suite" if picked == ALL else (", ".join(ordered(picked)) or "static checks only")
            log(f"  {path}: {label} ({why})")
        if not changed:
            # Nothing to scope by (an empty diff): take no chances.
            suites = ALL
            log("no changed files: every suite runs")
    names = ordered(suites)
    skipped = [s for s in SUITES if s not in suites]
    log(f"running: {', '.join(names) or 'static checks only'}")
    if skipped:
        log(f"left out, no changed file is read by them: {', '.join(skipped)}")
    set_output("suites", json.dumps(names))
    set_output("skipped_suites", json.dumps(skipped))
    set_output("needs_browser", "true" if suites & BROWSER_SUITES else "false")
    set_output("guard_matrix", json.dumps(guard_matrix(suites)))
    return 0


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def cmd_required(args: argparse.Namespace) -> int:
    print(" ".join(required(json.loads(args.suites), _bool(args.browser_changed),
                            _bool(args.has_sundial))))
    return 0


def cmd_gate(_: argparse.Namespace) -> int:
    results = {name: job["result"] for name, job in json.loads(os.environ["RESULTS"]).items()}
    suites = json.loads(os.environ.get("SUITES") or "null")
    if suites is None:
        # resolve did not finish; nothing was scoped, so nothing may be skipped.
        suites = list(SUITES)
    problems = gate(results, suites, _bool(os.environ.get("BROWSER_CHANGED", "")),
                    _bool(os.environ.get("HAS_SUNDIAL", "")))

    width = max(len(n) for n in results)
    print("\ntier results:")
    for name, result in sorted(results.items()):
        mark = "ok  " if result == "success" else "FAIL"
        print(f"  {mark}  {name:<{width}}  {result}")
    if problems:
        print("\nnot mergeable:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nevery tier passed; this pull request is mergeable.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m ci.scope", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="the suites the changed files need")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="the pull request's base commit")
    group.add_argument("--all", metavar="EVENT", help="run everything; names the reason")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("required", help="result names summarize must see")
    p.add_argument("--suites", required=True)
    p.add_argument("--browser-changed", required=True)
    p.add_argument("--has-sundial", required=True)
    p.set_defaults(fn=cmd_required)
    p = sub.add_parser("gate", help="the merge gate (reads RESULTS, SUITES, BROWSER_CHANGED, HAS_SUNDIAL)")
    p.set_defaults(fn=cmd_gate)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
