"""The build-tester gate fails on launch errors, missing profiles and unexplained exits.

Profiles are shaped as browser/tests/build-tester/scripts/runner.py writes
them: no index, a display name, and raw pass/total counts.
"""

from __future__ import annotations

import json

from .test_ci import _build_tester_run


def _profile_run(tmp_path, monkeypatch, profiles, code=None, profile_count=8):
    """Run the gate with a child that writes `profiles`; returns (exit code, status).

    The child exits as runner.py does unless `code` is given: 0 when the raw
    totals agree, 1 otherwise.
    """
    import ci.run_build_tester as bt
    from ci._util import Result

    monkeypatch.setattr(bt, "CONFIG_PATH", tmp_path / "bt.yml")
    (tmp_path / "bt.yml").write_text(f"profile_count: {profile_count}\n")
    passed = sum(p["passCount"] for p in profiles)
    total = sum(p["totalChecks"] for p in profiles)
    exit_code = (0 if passed == total else 1) if code is None else code

    def child(cmd, **kw):
        (tmp_path / "build-tester-result.json").write_text(
            json.dumps({"profiles": profiles, "totalPassed": passed, "totalChecks": total}))
        return Result(exit_code, "", "")

    gate_code = _build_tester_run(tmp_path, monkeypatch, child)
    saved = json.loads(next((tmp_path / "evidence").glob("*.json")).read_text())
    return gate_code, saved["status"]


def _launched(name, os_name="linux", mode="per-context", failed_checks=0):
    return {"profile": {"name": name, "os": os_name, "mode": mode},
            "results": {"webrtc": {"passed": True}},
            "passCount": 10 - failed_checks, "totalChecks": 10}


def _crashed(name, os_name="linux", mode="per-context"):
    return {"profile": {"name": name, "os": os_name, "mode": mode},
            "results": None, "error": "browser crashed", "passCount": 0, "totalChecks": 0}


def _default_run():
    """The eight profiles runner.py launches: three per-context and one global per OS."""
    return ([_launched(f"macOS Per-Context {c}", "macos") for c in "ABC"]
            + [_launched(f"Linux Per-Context {c}") for c in "ABC"]
            + [_launched("macOS Global", "macos", "global"), _launched("Linux Global", mode="global")])


def test_build_tester_passes_a_default_run_whose_profiles_carry_no_index(tmp_path, monkeypatch):
    assert _profile_run(tmp_path, monkeypatch, _default_run()) == (0, "pass")


def test_build_tester_fails_when_a_profile_did_not_launch(tmp_path, monkeypatch):
    profiles = _default_run()
    profiles[0] = _crashed("macOS Per-Context A", "macos")  # a later macOS slot launched
    assert _profile_run(tmp_path, monkeypatch, profiles) == (1, "fail")


def test_build_tester_fails_when_fewer_profiles_than_configured_ran(tmp_path, monkeypatch):
    assert _profile_run(tmp_path, monkeypatch, _default_run()[:7]) == (1, "fail")


def test_build_tester_fails_on_an_unexplained_nonzero_exit(tmp_path, monkeypatch):
    assert _profile_run(tmp_path, monkeypatch, _default_run(), code=3) == (1, "fail")


def test_build_tester_tolerates_the_exit_code_of_checks_it_does_not_gate(tmp_path, monkeypatch):
    """runner.py exits 1 on any raw failure; ones outside required_categories are not gated."""
    profiles = _default_run()
    profiles[1] = _launched("macOS Per-Context B", "macos", failed_checks=1)
    assert _profile_run(tmp_path, monkeypatch, profiles) == (0, "pass")
