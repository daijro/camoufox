"""ci/scope.py: a pull request runs the suites that read what it changes."""

from __future__ import annotations

import json
import re

import pytest
import yaml

from ci import scope
from ci._util import REPO_ROOT
from ci.scope import ALL, SUITES

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _suites(*changed: str) -> set:
    return set(scope.select(changed)[0])


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------


def test_a_release_pipeline_fix_runs_only_the_static_checks():
    """#816: release.yml and its test. Nothing a suite reads."""
    picked = scope.select([".github/workflows/release.yml", "ci/tests/test_release.py"])[0]
    assert picked == frozenset()
    assert scope.guard_matrix(picked) == []
    assert not picked & scope.BROWSER_SUITES


def test_prose_runs_nothing():
    assert _suites("docs/releasing.md", "README.md", "ci/README.md", "LICENSE") == set()


def test_a_pythonlib_change_skips_the_upstream_playwright_suite():
    """That suite drives the binary through playwright-python, never pythonlib."""
    picked = _suites("pythonlib/camoufox/utils.py")
    assert "playwright" not in picked and "skiplist-audit" not in picked
    # ...but everything that launches through pythonlib, and the TS golden
    # tests that hold typescript/ to pythonlib's output, still run.
    assert {"pythonlib", "typescript", "patch-guards", "build-tester", "native", "growth",
            "sundial", "typescript-browser"} <= picked


def test_a_typescript_change_runs_the_typescript_suites():
    assert _suites("typescript/src/index.ts") == {"typescript", "typescript-browser"}


@pytest.mark.parametrize("path", [
    "patches/fingerprint-injection.patch", "additions/juggler/TargetRegistry.js",
    "settings/camoufox.cfg", "upstream.sh", "Makefile", "scripts/patch.py",
])
def test_a_browser_source_runs_everything(path):
    assert scope.classify(path)[0] == ALL


@pytest.mark.parametrize("path", [
    "Dockerfile", "multibuild.py", "bundle/fontconfig/fonts.conf", "service-tester/x.py",
    "a-new-top-level-dir/thing.py", "ci/something_new.py", ".github/workflows/new.yml",
])
def test_a_path_no_rule_covers_runs_everything(path):
    """Fail closed: a missing rule costs time, never coverage."""
    suites, why = scope.classify(path)
    assert suites == ALL, why


@pytest.mark.parametrize("path", [
    ".github/workflows/tests.yml", ".github/actions/prepare-browser/action.yml",
    "ci/_util.py", "ci/results.py", "ci/summarize.py", "ci/scope.py", "ci/requirements.txt",
])
def test_the_pipeline_itself_runs_everything(path):
    assert scope.classify(path)[0] == ALL


def test_one_file_that_needs_everything_wins():
    assert _suites("docs/x.md", "pythonlib/camoufox/utils.py", "Dockerfile") == ALL


def test_a_libraries_readme_is_still_its_library():
    """First match wins: pythonlib/README.md ships in the wheel, so it is pythonlib's."""
    assert _suites("pythonlib/README.md") == set(scope.PYTHONLIB_READERS)


def test_the_guard_matrix_holds_exactly_the_selected_legs():
    assert [leg["leg"] for leg in scope.guard_matrix({"skiplist-audit"})] == ["skiplist"]
    assert [leg["leg"] for leg in scope.guard_matrix({"patch-guards"})] == \
        ["spoofing", "automation", "parity"]
    assert len(scope.guard_matrix(ALL)) == 4


def test_every_rule_names_real_suites():
    for pattern, suites in scope.RULES:
        assert suites <= ALL, pattern


# ---------------------------------------------------------------------------
# the plan command
# ---------------------------------------------------------------------------


def _outputs(tmp_path, monkeypatch, *argv) -> dict:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert scope.main(["plan", *argv]) == 0
    return dict(line.split("=", 1) for line in out.read_text().splitlines())


def test_anything_but_a_pull_request_runs_everything(tmp_path, monkeypatch):
    got = _outputs(tmp_path, monkeypatch, "--all", "push")
    assert json.loads(got["suites"]) == list(SUITES)
    assert json.loads(got["skipped_suites"]) == []
    assert got["needs_browser"] == "true"
    assert len(json.loads(got["guard_matrix"])) == 4


def test_an_empty_diff_runs_everything(tmp_path, monkeypatch):
    got = _outputs(tmp_path, monkeypatch, "--base", "HEAD")
    assert json.loads(got["suites"]) == list(SUITES)


# ---------------------------------------------------------------------------
# the summary and the gate
# ---------------------------------------------------------------------------


def test_only_the_selected_suites_are_required():
    assert scope.required([], browser_changed=False, has_sundial=True) == ["native_rules"]
    req = scope.required(["typescript", "typescript-browser"], browser_changed=False, has_sundial=True)
    assert set(req) == {"native_rules", "typescript", "typescript_browser"}


def test_build_is_required_only_when_a_selected_suite_needed_the_built_browser():
    assert "build" in scope.required(ALL, browser_changed=True, has_sundial=False)
    assert "build" not in scope.required(["pythonlib"], browser_changed=True, has_sundial=False)


def _needs(**results) -> dict:
    base = {job: "success" for job in _jobs()["gate"]["needs"]}
    base.update({k.replace("_", "-"): v for k, v in results.items()})
    return base


def test_the_gate_lets_an_unselected_suite_skip():
    results = _needs(playwright="skipped", patch_guards="skipped", growth="skipped",
                     build="skipped", fetch_browser="skipped", native="skipped",
                     build_tester="skipped", typescript_browser="skipped", sundial="skipped")
    assert scope.gate(results, ["pythonlib", "typescript"], False, True) == []


def test_the_gate_fails_a_selected_suite_that_skipped():
    """Selected and not run is not passed -- e.g. its tier-3a gate was skipped by mistake."""
    results = _needs(build="skipped", playwright="skipped")
    assert scope.gate(results, list(SUITES), False, True) == ["playwright: skipped"]


def test_the_gate_fails_a_fetch_skipped_when_a_browser_was_needed():
    results = _needs(build="skipped", fetch_browser="skipped")
    assert scope.gate(results, list(SUITES), False, True) == ["fetch-browser: skipped"]


def test_the_gate_allows_sundial_to_skip_without_a_credential():
    results = _needs(build="skipped", sundial="skipped")
    assert scope.gate(results, list(SUITES), False, False) == []
    assert scope.gate(results, list(SUITES), False, True) == ["sundial: skipped"]


def test_the_gate_fails_closed_when_resolve_produced_no_scope(monkeypatch, capsys):
    monkeypatch.setenv("RESULTS", json.dumps({n: {"result": r} for n, r in
                                              _needs(resolve="failure", playwright="skipped").items()}))
    monkeypatch.setenv("SUITES", "")
    assert scope.main(["gate"]) == 1


# ---------------------------------------------------------------------------
# the workflow agrees with the module
# ---------------------------------------------------------------------------


def test_every_suite_has_a_job_that_asks_for_it():
    jobs = _jobs()
    covered = set()
    for job, suites in scope.JOB_SUITES.items():
        assert job in jobs, f"ci/scope.py schedules {job}, which tests.yml does not have"
        covered |= suites
        cond = str(jobs[job].get("if", ""))
        if job == "patch-guards":
            assert "guard_matrix" in cond and "guard_matrix" in json.dumps(jobs[job]["strategy"])
        else:
            (suite,) = suites
            assert f"contains(fromJSON(needs.resolve.outputs.suites), '{suite}')" in cond, job
    assert covered == ALL


def test_the_gate_waits_on_every_scoped_job():
    needs = set(_jobs()["gate"]["needs"])
    assert set(scope.JOB_SUITES) <= needs
    assert "python3 -m ci.scope gate" in json.dumps(_jobs()["gate"]["steps"])


def test_every_result_name_is_one_summarize_knows():
    """RESULT_NAMES must be names a runner writes (see test_ci's producible list)."""
    names = {n for group in scope.RESULT_NAMES.values() for n in group}
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 -m ci.scope required" in text
    assert names == {
        "pythonlib", "typescript", "typescript_browser", "patch_guards_spoofing",
        "patch_guards_automation", "patch_guards_parity", "skiplist_audit", "build_tester",
        "playwright", "native_browser", "native_growth", "sundial",
    }


def test_the_workflows_matrix_legs_are_the_modules():
    """The legs the guards runner and summarize expect, titles unchanged."""
    from ci.run_patch_guards import GROUPS

    assert {leg["leg"] for leg in scope.GUARD_LEGS} == set(GROUPS) | {"skiplist"}


# ---------------------------------------------------------------------------
# implicit success() -- the release.yml bug, in this workflow
# ---------------------------------------------------------------------------


def test_no_job_is_skipped_because_something_upstream_of_it_was():
    """A job whose `if` has no status function gets an implicit success(), which
    is false when ANY job upstream of it was skipped -- not only its direct
    needs. Scoping makes almost every job skippable, so everything downstream of
    a job with an `if` must say always() or !cancelled() and check what it
    actually depends on."""
    jobs = _jobs()

    def needs(name):
        n = jobs[name].get("needs", [])
        return [n] if isinstance(n, str) else n

    def upstream(name):
        seen, stack = set(), list(needs(name))
        while stack:
            job = stack.pop()
            if job not in seen:
                seen.add(job)
                stack.extend(needs(job))
        return seen

    skippable = {name for name, job in jobs.items() if "if" in job}
    unguarded = [
        name for name in sorted(jobs)
        if upstream(name) & skippable
        and not re.search(r"!cancelled\(\)|always\(\)", str(jobs[name].get("if", "")))
    ]
    assert not unguarded, f"skipped whenever an upstream job is: {unguarded}"
