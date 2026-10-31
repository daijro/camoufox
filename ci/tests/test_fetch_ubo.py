"""browser/scripts/fetch-ubo.py: every package bundles AMO's newest uBlock Origin,
checked, and a release bundles the one its tests ran with."""

import hashlib
import importlib.util
import io
import json
import zipfile

import pytest
import yaml

from ci._util import BROWSER_ROOT, REPO_ROOT

spec = importlib.util.spec_from_file_location("fetch_ubo", BROWSER_ROOT / "scripts" / "fetch-ubo.py")
fetch_ubo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_ubo)

GUID = "uBlock0@raymondhill.net"


def xpi(version="1.76.0", guid=GUID, extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(
            {"version": version, "browser_specific_settings": {"gecko": {"id": guid}}}))
        z.writestr("js/background.js", "")
        for name in extra:
            z.writestr(name, "")
    return buf.getvalue()


def amo(data, version="1.76.0", guid=GUID, algorithm="sha256"):
    digest = hashlib.sha256(data).hexdigest()
    return {"guid": guid, "current_version": {"version": version, "file": {
        "url": f"https://addons.mozilla.org/firefox/downloads/file/1/ublock_origin-{version}.xpi",
        "hash": f"{algorithm}:{digest}"}}}


def test_the_pin_is_amo_s_current_release():
    data = xpi()
    pin = fetch_ubo.pin_from_amo(amo(data))
    assert pin == {"version": "1.76.0", "sha256": hashlib.sha256(data).hexdigest(),
                   "url": "https://addons.mozilla.org/firefox/downloads/file/1/ublock_origin-1.76.0.xpi"}


@pytest.mark.parametrize("record", [amo(b"", guid="evil@example.com"), amo(b"", algorithm="sha1")])
def test_another_addon_or_a_weaker_hash_is_refused(record):
    with pytest.raises(SystemExit):
        fetch_ubo.pin_from_amo(record)


def test_stage_extracts_the_pinned_release_beside_the_binary(tmp_path, monkeypatch):
    data = xpi()
    pin = fetch_ubo.pin_from_amo(amo(data))
    monkeypatch.setenv("CAMOUFOX_UBO", json.dumps(pin))
    monkeypatch.setattr(fetch_ubo, "resolve", lambda: pytest.fail("a release's pin must not be re-resolved"))
    monkeypatch.setattr(fetch_ubo, "get", lambda url, timeout: data if url == pin["url"] else pytest.fail(url))
    (tmp_path / "addons" / "UBO").mkdir(parents=True)
    (tmp_path / "addons" / "UBO" / "stale.js").write_text("")
    fetch_ubo.stage(str(tmp_path))
    ubo = tmp_path / "addons" / "UBO"
    assert json.loads((ubo / "manifest.json").read_text())["version"] == "1.76.0"
    assert sorted(p.name for p in ubo.iterdir()) == ["js", "manifest.json"], "the previous copy is replaced"
    assert [p.name for p in (tmp_path / "addons").iterdir()] == ["UBO"], "no staging directory is left"


@pytest.mark.parametrize("data, pin_data, why", [
    (xpi(), xpi(version="1.76.1"), "sha256"),
    (xpi(guid="evil@example.com"), None, "not uBlock0"),
    (xpi(version="1.75.0"), None, "not uBlock0"),
    (xpi(extra=["../escape"]), None, "outside the addon"),
])
def test_a_download_that_is_not_the_pinned_release_is_refused(tmp_path, data, pin_data, why):
    pin = {"version": "1.76.0", "url": "u", "sha256": hashlib.sha256(pin_data or data).hexdigest()}
    with pytest.raises(SystemExit, match=why):
        fetch_ubo.extract(data, pin, str(tmp_path / "addons" / "UBO"))
    assert not (tmp_path / "addons" / "UBO").exists()


def test_packaging_bundles_it_where_the_launchers_look():
    package = (BROWSER_ROOT / "scripts" / "package.py").read_text(encoding="utf-8")
    assert "'fetch-ubo.py'), 'stage', target_dir" in package
    assert fetch_ubo.ADDON_DIR.replace("\\", "/") == "addons/UBO"


def test_a_release_bundles_the_ubo_its_tests_ran_with():
    """One resolve per cut, handed to the tests, every build and the manifest."""
    workflows = REPO_ROOT / ".github" / "workflows"
    jobs = yaml.safe_load((workflows / "release.yml").read_text(encoding="utf-8"))["jobs"]
    pin = "${{ needs.ubo.outputs.pin }}"
    assert any("fetch-ubo.py resolve" in s.get("run", "") for s in jobs["ubo"]["steps"])
    assert jobs["tests"]["with"]["ubo"] == pin
    assert "ubo" in jobs["build-browser"]["needs"]
    assert jobs["build-browser"]["env"]["CAMOUFOX_UBO"] == pin
    publish = next(s for s in jobs["publish-browser"]["steps"] if "ci.release manifest" in s.get("run", ""))
    assert publish["env"]["UBO"] == pin and '--ubo "$UBO"' in publish["run"]

    tests = yaml.safe_load((workflows / "tests.yml").read_text(encoding="utf-8"))
    call = tests[True]["workflow_call"]["inputs"]  # PyYAML reads the `on:` key as True
    assert "ubo" in call
    resolve = tests["jobs"]["resolve"]
    assert resolve["outputs"]["ubo"] == "${{ steps.ubo.outputs.pin }}"
    step = next(s for s in resolve["steps"] if s.get("id") == "ubo")
    assert step["env"]["CAMOUFOX_UBO"] == "${{ inputs.ubo }}"
    build = tests["jobs"]["build"]["steps"]
    staged = [s for s in build if "fetch-ubo.py stage" in s.get("run", "")]
    assert len(staged) == 2, "both the built and the restored browser bundle this run's uBO"
    assert all(s["env"]["CAMOUFOX_UBO"] == "${{ needs.resolve.outputs.ubo }}" for s in staged)


def test_the_manifest_names_the_bundled_ubo():
    from ci import release

    pin = {"version": "1.76.0", "url": "u", "sha256": "0" * 64}
    assert release.manifest("v1", "d", "0" * 40, pin)["ubo"] == pin
    assert "ubo" not in release.manifest("v1", "d", "0" * 40)
