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


_HANGING_MULTIBUILD = """import pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pathlib.Path("child.pid").write_text(str(child.pid))
print("building", flush=True)
time.sleep(60)
"""


def test_a_build_past_its_timeout_is_ended_with_its_children(tmp_path, monkeypatch):
    (tmp_path / "multibuild.py").write_text(_HANGING_MULTIBUILD)
    monkeypatch.setattr(run_build, "BROWSER_ROOT", tmp_path)
    monkeypatch.setattr(run_build, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(run_build, "read_upstream_sh", lambda: {})

    code = run_build.main(["--evidence-dir", str(tmp_path / "out"), "--timeout", "2"])

    saved = json.loads(next((tmp_path / "out").glob("*.json")).read_text())
    assert (code, saved["metrics"]["exit_code"]) == (1, 124)
    assert _gone(int((tmp_path / "child.pid").read_text()))


def _gone(pid, wait=5.0):
    """Whether `pid` has exited (a zombie awaiting its reaper counts) within `wait` seconds."""
    import time
    from pathlib import Path

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            if Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z":
                return True
        except FileNotFoundError:
            return True
        time.sleep(0.1)
    return False


def test_a_relative_work_dir_still_holds_the_log(tmp_path, monkeypatch):
    (tmp_path / "browser").mkdir()
    (tmp_path / "browser" / "multibuild.py").write_text(_FAKE_MULTIBUILD)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_build, "BROWSER_ROOT", tmp_path / "browser")
    monkeypatch.setattr(run_build, "WORK_DIR", run_build.Path(".ci-work"))
    monkeypatch.setattr(run_build, "read_upstream_sh", lambda: {})

    code = run_build.main(["--evidence-dir", str(tmp_path / "out")])

    saved = json.loads(next((tmp_path / "out").glob("*.json")).read_text())
    assert (code, saved["metrics"]["error_count"]) == (1, 2)
    assert "compiling" in (tmp_path / ".ci-work" / "build.log").read_text()
