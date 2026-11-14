#!/usr/bin/env python3
"""Find the pull request run that already tested the tree a push to main landed.

A pull request run tests the pull request merged into main as main stood then.
When nothing else merged before it, the squashed commit on main has exactly that
tree, and testing it again proves nothing new. Each pull request run records its
tree as an artifact (`tested-tree-<tree>`, tests.yml's resolve job); a push to
main looks for a passing run of the merged pull request's head that recorded
main's tree, and carries its results instead of re-running them.

The run must still hold the browser it tested (`camoufox-dist`, kept three
days): the suites a pull request from a fork cannot run, the stealth check,
run on main against it.

    python3 -m ci.carry --sha <main commit>
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from ci._util import gh_headers, http_json, run, set_output
from ci.release import REPO_ROOT, repo_name

API = "https://api.github.com"
TREE_ARTIFACT = "tested-tree-"


@dataclass
class Carry:
    run_id: int
    built: bool  # the run compiled its browser, rather than fetching a release


def _pages(get: Callable[[str], dict], url: str, key: str) -> List[dict]:
    items: List[dict] = []
    for page in range(1, 11):
        batch = get(f"{url}{'&' if '?' in url else '?'}per_page=100&page={page}")[key]
        items += batch
        if len(batch) < 100:
            break
    return items


def find(sha: str, tree: str, get: Callable[[str], object]) -> tuple[Optional[Carry], str]:
    """The run to carry for main commit `sha` with tree `tree`, and why (not)."""
    repo = f"{API}/repos/{repo_name()}"
    merged = [p for p in get(f"{repo}/commits/{sha}/pulls") if p.get("merge_commit_sha") == sha]
    if not merged:
        return None, f"no pull request was merged as {sha[:10]}"
    pr = merged[0]
    runs = _pages(get, f"{repo}/actions/workflows/tests.yml/runs?event=pull_request"
                       f"&status=success&head_sha={pr['head']['sha']}", "workflow_runs")
    for wf in sorted(runs, key=lambda r: r["id"], reverse=True):
        artifacts = {a["name"] for a in _pages(get, f"{repo}/actions/runs/{wf['id']}/artifacts", "artifacts")
                     if not a["expired"]}
        if TREE_ARTIFACT + tree not in artifacts:
            continue
        if "camoufox-dist" not in artifacts:
            return None, f"run {wf['id']} of #{pr['number']} tested this tree, but its browser has expired"
        return Carry(wf["id"], "results-build" in artifacts), f"run {wf['id']} of #{pr['number']} tested this tree"
    return None, f"no passing run of #{pr['number']} tested this tree; main moved after it ran"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sha", required=True)
    args = ap.parse_args(argv)
    tree = run(["git", "rev-parse", f"{args.sha}^{{tree}}"], cwd=REPO_ROOT, check=True).stdout.strip()
    carry, why = find(args.sha, tree, lambda url: http_json(url, headers=gh_headers()))
    print(f"::notice::{'Carrying' if carry else 'Testing in full'}: {why}.")
    set_output("run", str(carry.run_id) if carry else "")
    set_output("built", "true" if carry and carry.built else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
