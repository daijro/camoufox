#!/usr/bin/env python3
"""Fold every result file into one verdict and one readable table.

Runs last in CI. Three jobs:

  * **Merge shards.** The upstream suite is split across parallel runners, so
    `playwright-3of6` and its siblings are folded back into one record
    before anything is judged.
  * **Decide.** A required suite that produced no result file is a failure, not
    a skip -- otherwise deleting a job would be the cheapest way to a green
    tick. Anything that failed is a failure.
  * **Report.** Writes the Markdown that lands in the job summary and the pull
    request. The stealth line is a grade and a count; it never names a vector.

It also validates `ci/skiplist.yml`: an entry with no reason fails the run,
because a skiplist that can grow silently is a way to make any test disappear.

Run:
    python3 -m ci.summarize --results-dir .ci-work/results
    python3 -m ci.summarize --require build playwright --markdown out.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from . import results
from ._util import REPO_ROOT, RESULTS_DIR, SKIPLIST_PATH, log, summary, write_json

# "playwright-3of6" -> "playwright"
_SHARD_SUFFIX = re.compile(r"-\d+of\d+$")

# Presented in this order; anything unexpected is appended.
_ORDER = [
    "native_rules", "pythonlib", "patches_apply", "build", "patch_guards",
    "skiplist_audit", "native_browser", "build_tester", "playwright", "sundial",
]


def merge_shards(records: Dict[str, dict]) -> Dict[str, dict]:
    """Fold `<name>-<i>of<n>` records back into `<name>`."""
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for name, record in records.items():
        grouped[_SHARD_SUFFIX.sub("", name)].append(record)

    merged: Dict[str, dict] = {}
    for name, parts in grouped.items():
        if len(parts) == 1:
            merged[name] = parts[0]
            continue
        tests: Dict[str, str] = {}
        notes: List[str] = []
        artifacts: List[str] = []
        metrics: Dict[str, object] = {}
        statuses = []
        for part in sorted(parts, key=lambda p: str(p.get("gate"))):
            for tid, outcome in (part.get("tests") or {}).items():
                # A test that passed on any shard passed; shards are disjoint,
                # so this only matters if a retry moved one.
                if tests.get(tid) != results.PASS:
                    tests[tid] = outcome
            notes.extend(part.get("notes") or [])
            artifacts.extend(part.get("artifacts") or [])
            statuses.append(part.get("status"))
            for key, value in (part.get("metrics") or {}).items():
                metrics.setdefault(key, value)
        metrics.pop("shard", None)
        metrics["shards"] = len(parts)
        tally: Dict[str, int] = {}
        for outcome in tests.values():
            tally[outcome] = tally.get(outcome, 0) + 1
        tally["total"] = len(tests)
        metrics["tally"] = tally
        merged[name] = {
            "gate": name,
            "status": (
                results.ERROR if results.ERROR in statuses
                else results.FAIL if results.FAIL in statuses
                else results.PASS
            ),
            "tests": tests,
            "metrics": metrics,
            "notes": notes,
            "artifacts": artifacts,
            "run_id": parts[0].get("run_id"),
        }
        log(f"merged {len(parts)} shards of {name}: {tally.get('total', 0)} tests")
    return merged


def validate_skiplist(path: Optional[Path] = None) -> List[str]:
    """Every skip needs a reason, and every `replaced-by` has to point at a real
    file. Returns the problems found.

    The second check is what keeps the "upstream expectations that encode a
    stock-Firefox quirk" section honest. Those entries claim a Camoufox-owned
    test took over guarding the behaviour; if that file is renamed or deleted the
    claim silently becomes false and the behaviour stops being tested by anything.
    """
    path = path or SKIPLIST_PATH
    if not path.exists():
        return []
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems = []
    for index, entry in enumerate(data.get("skip") or []):
        if not isinstance(entry, dict):
            problems.append(f"skiplist entry {index} is not a mapping")
            continue
        target = entry.get("module") or entry.get("test") or entry.get("pattern")
        if not target:
            problems.append(f"skiplist entry {index} names no module, test or pattern")
        if not str(entry.get("reason", "")).strip():
            problems.append(
                f"skiplist entry {target!r} has no reason. A skip without a stated reason "
                "is indistinguishable from hiding a failure."
            )
        replacement = str(entry.get("replaced-by", "")).strip()
        if replacement and not (REPO_ROOT / replacement).is_file():
            problems.append(
                f"skiplist entry {target!r} says it is replaced by {replacement!r}, "
                "which does not exist. Either restore that test or stop claiming "
                "the behaviour is still covered."
            )
    return problems


def _firefox_generation(browser_version: str) -> str:
    """`152.0.4` -> `152`. A missing or malformed version is not worth failing on."""
    head = browser_version.split(".")[0].strip()
    return head if head.isdigit() else "?"


def render(merged: Dict[str, dict], required: List[str], problems: List[str], meta: Dict[str, str]) -> str:
    ok = not problems
    lines = [
        "## " + ("✅ Tests passed" if ok else "❌ Tests failed"),
        "",
        f"Camoufox `{meta.get('browser_version', '?')}` "
        f"(`{meta.get('browser_release') or 'no release tag'}`), built on Firefox "
        f"`{_firefox_generation(meta.get('browser_version', ''))}`, tested against Playwright "
        f"`{meta.get('playwright_tag', '?')}` — "
        # Say WHY that tag, because the Firefox it pins is rarely the Firefox
        # being tested and the bare pair reads like a mismatch. Playwright
        # releases trail Firefox and skip generations (it went 151 -> 153,
        # never pinning 152), so an exact match is the exception.
        + (meta.get("version_note") or f"which targets Firefox `{meta.get('playwright_firefox', '?')}`")
        + ".",
        "",
        "| Suite | Result | Detail |",
        "| --- | --- | --- |",
    ]

    ordered = [n for n in _ORDER if n in merged] + [n for n in merged if n not in _ORDER]
    for name in ordered:
        record = merged[name]
        status = record.get("status", "error")
        icon = {"pass": "✅", "fail": "❌", "error": "💥"}.get(status, "❓")
        tally = (record.get("metrics") or {}).get("tally") or {}
        if name == "sundial":
            # Grade and counts only. Never a category, never a vector.
            # Named distinctly from the shard `metrics` above so the self-test
            # can hold just these reads to sundial's publishable whitelist.
            sundial_metrics = record.get("metrics") or {}
            detail = (
                f"grade **{sundial_metrics.get('grade', '?')}** — "
                f"{sundial_metrics.get('checks_passed', 0)}"
                f"/{sundial_metrics.get('checks_total', 0)} "
                f"in-scope checks passed"
            )
        elif tally:
            failed = tally.get("fail", 0) + tally.get("error", 0)
            detail = f"{tally.get('pass', 0)} passed, {failed} failed, {tally.get('total', 0)} collected"
            shards = (record.get("metrics") or {}).get("shards")
            if shards:
                detail += f" (across {shards} shards)"
        else:
            detail = (record.get("notes") or ["—"])[-1]
        lines.append(f"| `{name}` | {icon} {status} | {detail} |")

    for name in required:
        if name not in merged:
            lines.append(f"| `{name}` | 🚫 missing | required, but produced no result |")

    if problems:
        lines += ["", "### What failed", ""]
        lines += [f"- {p}" for p in problems]

    lines += [
        "",
        "<sub>The Playwright suite is upstream playwright-python at the tag above, "
        "fetched fresh, run with main-world execution, with "
        "[`tests/camoufox/`](tests/camoufox) overlaid. Tests Camoufox cannot pass by "
        "design are deselected via [`ci/skiplist.yml`](ci/skiplist.yml) — each with a "
        "stated reason. The stealth check reports a grade only; its per-vector detail "
        "is deliberately never published.</sub>",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--require", nargs="*", default=[], help="suites that must have reported")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--browser-version", default="")
    parser.add_argument("--browser-release", default="")
    parser.add_argument("--playwright-tag", default="")
    parser.add_argument("--playwright-firefox", default="")
    parser.add_argument("--version-note", default="", help="how ci.versions chose the suite")
    parser.add_argument("--allow-failure", nargs="*", default=[],
                        help="suites whose failure is reported but not fatal")
    args = parser.parse_args(argv)

    records = results.load_all(args.results_dir)
    merged = merge_shards(records)
    problems: List[str] = []

    problems.extend(validate_skiplist())

    for name in args.require:
        if name not in merged:
            problems.append(
                f"`{name}` is required but produced no result file. A suite that did not "
                "run has not passed."
            )

    for name, record in sorted(merged.items()):
        if record.get("status") == results.PASS:
            continue
        if name in args.allow_failure:
            log(f"{name} failed but is advisory on this run", level="WARN")
            continue
        note = (record.get("notes") or ["see the job log"])[-1]
        problems.append(f"`{name}` reported {record.get('status')}: {note}")

    meta = {
        "browser_version": args.browser_version,
        "browser_release": args.browser_release,
        "playwright_tag": args.playwright_tag,
        "playwright_firefox": args.playwright_firefox,
        "version_note": args.version_note,
    }
    markdown = render(merged, args.require, problems, meta)
    print()
    print(markdown)
    print()
    summary(markdown)

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown + "\n", encoding="utf-8")
    if args.out:
        write_json(args.out, {
            "ok": not problems,
            "problems": problems,
            "suites": {
                name: {
                    "status": r.get("status"),
                    "metrics": r.get("metrics"),
                    "notes": r.get("notes"),
                }
                for name, r in merged.items()
            },
            **meta,
        })

    if problems:
        log(f"{len(problems)} problem(s)", level="ERROR")
        for problem in problems:
            log(f"  {problem}", level="ERROR")
        return 1
    log("all suites passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
