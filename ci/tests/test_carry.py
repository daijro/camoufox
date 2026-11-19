import json
import os
import subprocess

import yaml

from ci import carry
from ci.tests.test_ci import WORKFLOW

SHA, TREE, HEAD = "a" * 40, "t" * 40, "h" * 40
REPO = "https://api.github.com/repos/daijro/camoufox"


def _api(runs, artifacts, pulls=None):
    """A fake GitHub API: the merged pull request, its passing runs, their artifacts."""
    pulls = [{"number": 7, "merge_commit_sha": SHA, "head": {"sha": HEAD}}] if pulls is None else pulls

    def get(url):
        if url == f"{REPO}/commits/{SHA}/pulls":
            return pulls
        if url.startswith(f"{REPO}/actions/workflows/tests.yml/runs?"):
            assert f"head_sha={HEAD}" in url and "status=success" in url and "event=pull_request" in url
            return {"workflow_runs": [{"id": r} for r in runs]}
        run_id = int(url.split("/actions/runs/")[1].split("/")[0])
        return {"artifacts": [{"name": n, "expired": n.endswith("!")} for n in artifacts[run_id]]}
    return get


def test_a_run_that_tested_mains_tree_is_carried(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "daijro/camoufox")
    found, _ = carry.find(SHA, TREE, _api([5], {5: [f"tested-tree-{TREE}", "camoufox-dist", "results-build"]}))
    assert found == carry.Carry(5, built=True)
    found, _ = carry.find(SHA, TREE, _api([5], {5: [f"tested-tree-{TREE}", "camoufox-dist"]}))
    assert found == carry.Carry(5, built=False)


def test_the_newest_run_with_mains_tree_is_carried(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "daijro/camoufox")
    runs = {5: [f"tested-tree-{TREE}", "camoufox-dist"], 9: ["tested-tree-other", "camoufox-dist"],
            8: [f"tested-tree-{TREE}", "camoufox-dist"]}
    found, _ = carry.find(SHA, TREE, _api([5, 9, 8], runs))
    assert found.run_id == 8


def test_main_is_tested_in_full_when_it_moved_after_the_pull_request_ran(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "daijro/camoufox")
    found, why = carry.find(SHA, TREE, _api([5], {5: ["tested-tree-other", "camoufox-dist"]}))
    assert found is None and "main moved" in why


def test_main_is_tested_in_full_without_the_browser_the_run_tested(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "daijro/camoufox")
    found, why = carry.find(SHA, TREE, _api([5], {5: [f"tested-tree-{TREE}", "camoufox-dist!"]}))
    assert found is None and "expired" in why


def test_a_commit_no_pull_request_merged_is_tested_in_full(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "daijro/camoufox")
    found, _ = carry.find(SHA, TREE, _api([], {}, pulls=[{"number": 7, "merge_commit_sha": "b" * 40}]))
    assert found is None


def _gate(results, carried="", built="true", sundial="true"):
    step = next(s for s in yaml.safe_load(WORKFLOW.read_text())["jobs"]["gate"]["steps"]
                if s.get("name") == "Check every tier")
    env = {**os.environ, "RESULTS": json.dumps({k: {"result": v} for k, v in results.items()}),
           "BROWSER_CHANGED": built, "HAS_SUNDIAL": sundial, "CARRIED": carried}
    return subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True).returncode


JOBS = yaml.safe_load(WORKFLOW.read_text())["jobs"]["gate"]["needs"]
RERUN = {"resolve", "carry-browser", "sundial", "summary"}


def test_a_carried_run_passes_with_only_the_new_checks_run():
    results = {j: "success" if j in RERUN else "skipped" for j in JOBS}
    assert _gate(results, carried="5") == 0


def test_skipping_the_suites_fails_unless_the_run_was_carried():
    results = {j: "success" if j in RERUN else "skipped" for j in JOBS}
    assert _gate(results) != 0


def test_a_carried_run_still_fails_when_the_stealth_check_fails():
    results = {j: "success" if j in RERUN else "skipped" for j in JOBS}
    assert _gate({**results, "sundial": "failure"}, carried="5") != 0
