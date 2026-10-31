"""browser/scripts/pgo.py: every build gets stock's PGO profile for its Firefox."""

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

from ci._util import BROWSER_ROOT, read_upstream_sh

sys.path.insert(0, str(BROWSER_ROOT / "scripts"))
import pgo  # noqa: E402


def test_the_shipped_pin_covers_every_target_for_this_firefox():
    pin = json.loads((BROWSER_ROOT / "scripts" / "data" / "pgo-profiles.json").read_text())
    assert pin["firefox"] == read_upstream_sh()["version"]
    assert set(pin["profiles"]) == set(pgo.PROFILE_FOR.values())


def _archive(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Pins a profile for this Firefox and serves `body` as its download."""
    state = {"body": b"", "downloads": 0}

    def setup(body, sha256=None):
        state["body"] = body
        pin = tmp_path / "pin.json"
        entry = {"task": "T", "sha256": sha256 or hashlib.sha256(body).hexdigest()}
        pin.write_text(json.dumps({"firefox": "1.0", "commit": "c",
                                   "profiles": {p: entry for p in pgo.PROFILE_FOR.values()}}))
        monkeypatch.setattr(pgo, "PIN", str(pin))
        return entry["sha256"]

    def urlopen(url, timeout):
        state["downloads"] += 1
        return io.BytesIO(state["body"])

    monkeypatch.setenv("MOZBUILD_STATE_PATH", str(tmp_path / "mozbuild"))
    monkeypatch.setattr(pgo.urllib.request, "urlopen", urlopen)
    setup.state = state
    return setup


def test_the_profile_is_extracted_and_cached(served):
    sha = served(_archive({"merged.profdata": b"profile", "en-US.log": b"jar order",
                           "../escape": b"x"}))
    dest = pgo.fetch("linux", "arm64", "1.0")
    assert dest.endswith(sha)
    assert sorted(p.name for p in Path(dest).iterdir()) == ["en-US.log", "merged.profdata"]
    assert open(f"{dest}/merged.profdata", "rb").read() == b"profile"
    assert pgo.fetch("linux", "arm64", "1.0") == dest
    assert served.state["downloads"] == 1


def test_a_download_that_is_not_the_pinned_one_is_refused(served):
    served(_archive({"merged.profdata": b"p", "en-US.log": b"l"}), sha256="0" * 64)
    with pytest.raises(SystemExit, match="sha256"):
        pgo.fetch("windows", "x86_64", "1.0")


def test_a_pin_for_another_firefox_is_refused(served):
    served(_archive({"merged.profdata": b"p", "en-US.log": b"l"}))
    with pytest.raises(SystemExit, match="pgo.py pin"):
        pgo.fetch("macos", "arm64", "2.0")
