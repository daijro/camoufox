"""ci.run_build reports the compiler errors of a failed build."""

from __future__ import annotations

import json

from ci import run_build

_FAKE_MULTIBUILD = """import sys
print("compiling")
print("dom/foo.cpp:12:5: error: use of undeclared identifier 'bar'")
print("error[E0425]: cannot find value baz in this scope", file=sys.stderr)
sys.exit(2)
"""


def test_a_failed_build_lists_the_compiler_errors(tmp_path, monkeypatch):
    (tmp_path / "multibuild.py").write_text(_FAKE_MULTIBUILD)
    monkeypatch.setattr(run_build, "BROWSER_ROOT", tmp_path)
    monkeypatch.setattr(run_build, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(run_build, "read_upstream_sh", lambda: {})

    code = run_build.main(["--evidence-dir", str(tmp_path / "out")])

    saved = json.loads(next((tmp_path / "out").glob("*.json")).read_text())
    assert (code, saved["status"]) == (1, "fail")
    assert saved["metrics"]["exit_code"] == 2
    assert "dom/foo.cpp:12:5: error: use of undeclared identifier 'bar'" in saved["notes"]
    assert saved["metrics"]["error_count"] == 2
