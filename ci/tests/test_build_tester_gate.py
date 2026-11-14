"""The build-tester gate fails on launch errors, missing profiles and unexplained exits."""

from __future__ import annotations

import json

from .test_ci import _build_tester_run


def _profile_run(tmp_path, monkeypatch, profiles, code=0, profile_count=2):
    """Run the gate with a child that writes `profiles`; returns (exit code, status)."""
    import ci.run_build_tester as bt
    from ci._util import Result

    monkeypatch.setattr(bt, "CONFIG_PATH", tmp_path / "bt.yml")
    (tmp_path / "bt.yml").write_text(f"profile_count: {profile_count}\n")

    def child(cmd, **kw):
        (tmp_path / "build-tester-result.json").write_text(json.dumps({"profiles": profiles}))
        return Result(code, "", "")

    exit_code = _build_tester_run(tmp_path, monkeypatch, child)
    saved = json.loads(next((tmp_path / "evidence").glob("*.json")).read_text())
    return exit_code, saved["status"]


def _launched(index):
    return {"profile": {"os": "linux", "mode": "per-context", "index": index},
            "results": {"webrtc": {"passed": True}}}


def _crashed(index):
    return {"profile": {"os": "linux", "mode": "per-context", "index": index},
            "results": None, "error": "browser crashed"}


def test_build_tester_fails_when_a_profile_did_not_launch(tmp_path, monkeypatch):
    code, status = _profile_run(tmp_path, monkeypatch, [_launched(0), _crashed(1)], code=1)
    assert (code, status) == (1, "fail")


def test_build_tester_fails_when_fewer_profiles_than_configured_ran(tmp_path, monkeypatch):
    code, status = _profile_run(tmp_path, monkeypatch, [_launched(0)], profile_count=2)
    assert (code, status) == (1, "fail")


def test_build_tester_fails_on_an_unexplained_nonzero_exit(tmp_path, monkeypatch):
    code, status = _profile_run(tmp_path, monkeypatch, [_launched(0), _launched(1)], code=3)
    assert (code, status) == (1, "fail")


def test_build_tester_passes_when_every_profile_launched_and_the_suite_exited_clean(tmp_path, monkeypatch):
    code, status = _profile_run(tmp_path, monkeypatch, [_launched(0), _launched(1)])
    assert (code, status) == (0, "pass")


def test_build_tester_tolerates_the_exit_code_of_checks_it_does_not_gate(tmp_path, monkeypatch):
    """The suite exits 1 on any failed check; ones outside required_categories are not gated."""
    failing = _launched(1)
    failing["results"]["webrtc"] = {"passed": False}
    code, status = _profile_run(tmp_path, monkeypatch, [_launched(0), failing], code=1)
    assert (code, status) == (0, "pass")
