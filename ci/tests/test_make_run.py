"""`make run` must hand the browser valid JSON with debug switched on."""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest

from ci._util import REPO_ROOT

BROWSER = REPO_ROOT / "browser"


def _make_run(tmp_path, config):
    """Run `make run` against a fake `mach` that prints the CAMOU_CONFIG it got."""
    source = tmp_path / "src"
    source.mkdir()
    mach = source / "mach"
    mach.write_text('#!/bin/sh\nprintf "%s\n" "$CAMOU_CONFIG"\n', encoding="utf-8")
    mach.chmod(mach.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "home"  # `make run` wipes ~/.camoufox
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    env.pop("CAMOU_CONFIG", None)
    if config is not None:
        env["CAMOU_CONFIG"] = config
    return subprocess.run(
        ["make", "--silent", "--no-print-directory", "-C", str(BROWSER), "run", f"cf_source_dir={source}"],
        env=env, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("config, expected", [
    (None, {"debug": True}),
    ("", {"debug": True}),
    ("{}", {"debug": True}),
    ('{"a": 1}', {"a": 1, "debug": True}),
])
def test_make_run_passes_valid_json_with_debug(tmp_path, config, expected):
    proc = _make_run(tmp_path, config)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.splitlines()[-1]) == expected


def test_make_run_stops_on_a_config_that_is_not_json(tmp_path):
    proc = _make_run(tmp_path, "{")
    assert proc.returncode != 0
    assert proc.stdout == ""  # mach, which prints its config, never ran
