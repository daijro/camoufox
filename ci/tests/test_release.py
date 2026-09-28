"""The release plan: which versions a merge or a tag publishes, and which browser they pair with."""

import argparse
import json
import re
import shutil

import pytest

from ci import browser_inputs, release
from ci.release import (
    DIGEST_MARKER,
    marker,
    next_browser_release,
    paired_release,
    plan_prerelease,
    plan_stable,
)

PYPI = ["0.5.5", "0.5.6", "0.5.6b1"]
NPM = ["0.5.6"]


def test_a_merge_prereleases_the_checked_in_version_when_it_is_unreleased():
    plan = plan_prerelease("0.5.7", PYPI, NPM)
    assert (plan.py, plan.npm, plan.dist_tag) == ("0.5.7b1", "0.5.7-beta.1", "next")


def test_prerelease_numbers_count_up_across_both_registries():
    assert plan_prerelease("0.5.7", PYPI + ["0.5.7b1", "0.5.7b2"], NPM).py == "0.5.7b3"
    assert plan_prerelease("0.5.7", PYPI, NPM + ["0.5.7-beta.4"]).npm == "0.5.7-beta.5"


def test_after_a_release_the_next_prerelease_is_of_the_next_patch():
    """Never 0.5.7b3 after 0.5.7 shipped: pip would rank it below the release."""
    plan = plan_prerelease("0.5.7", PYPI + ["0.5.7"], NPM + ["0.5.7"])
    assert plan.py == "0.5.8b1"


def test_a_tag_publishes_its_own_version_as_latest():
    plan = plan_stable("v0.5.7", PYPI, NPM)
    assert (plan.py, plan.npm, plan.dist_tag) == ("0.5.7", "0.5.7", "latest")


@pytest.mark.parametrize("tag,why", [
    ("v0.5.6", "already published"),
    ("v0.5.4", "not newer"),
    ("v156.0.1-beta.33", "not a release tag"),
    ("0.5.7", "not a release tag"),
])
def test_a_tag_that_cannot_be_a_release_is_refused(tag, why):
    with pytest.raises(ValueError, match=why):
        plan_stable(tag, PYPI, NPM)


def test_browser_release_numbers_are_global_and_never_reused():
    tags = ["v152.0.4-beta.30", "v152.0.4-beta.31", "v156.0.1-beta.33", "v152.0.2-alpha.1", "font-bundle-v1"]
    assert next_browser_release("beta.32", tags) == "beta.34"
    assert next_browser_release("beta.40", tags) == "beta.40"  # upstream.sh is the floor
    assert next_browser_release("beta.32", []) == "beta.32"


def test_a_library_pairs_with_the_newest_non_draft_release_from_its_sources():
    releases = [
        {"tag_name": "v156.0.1-beta.35", "draft": True, "body": marker(DIGEST_MARKER, "aaa")},
        {"tag_name": "v156.0.1-beta.34", "body": "notes\n" + marker(DIGEST_MARKER, "bbb")},
        {"tag_name": "v156.0.1-beta.33", "body": marker(DIGEST_MARKER, "aaa") + "\nnotes"},
        {"tag_name": "v152.0.4-beta.31", "body": None},
    ]
    assert paired_release(releases, "aaa")["tag_name"] == "v156.0.1-beta.33"
    assert paired_release(releases, "ccc") is None


def _copy_browser_inputs(tmp_path):
    root = tmp_path / "repo"
    for name in browser_inputs.BROWSER_DIRS:
        if (browser_inputs.REPO_ROOT / name).is_dir():
            shutil.copytree(browser_inputs.REPO_ROOT / name, root / name)
    for name in browser_inputs.BROWSER_FILES:
        shutil.copy(browser_inputs.REPO_ROOT / name, root / name)
    return root


def test_the_source_digest_ignores_the_release_number_and_nothing_else(tmp_path):
    root = _copy_browser_inputs(tmp_path)
    before = browser_inputs.source_digest(root)
    up = root / "upstream.sh"
    up.write_text(re.sub(r"^release=.*$", "release=beta.999", up.read_text(), flags=re.M))
    assert browser_inputs.source_digest(root) == before

    juggler = next((root / "additions" / "juggler").rglob("*.js"))
    juggler.write_text(juggler.read_text() + "\n")
    assert browser_inputs.source_digest(root) != before, "a packaged resource is a browser source"

    up.write_text(up.read_text().replace("version=", "version=999", 1))
    assert browser_inputs.source_digest(root) != before


def test_stamp_writes_the_pin_and_every_version(tmp_path, monkeypatch):
    for name, src in [("PIN_FILE", release.PIN_FILE), ("PYPROJECT", release.PYPROJECT),
                      ("PACKAGE_JSON", release.PACKAGE_JSON), ("TS_VERSION", release.TS_VERSION)]:
        dst = tmp_path / src.name
        shutil.copy(src, dst)
        monkeypatch.setattr(release, name, dst)
    monkeypatch.setenv("GITHUB_REPOSITORY", "daijro/camoufox")

    release.cmd_stamp(argparse.Namespace(browser_tag="v156.0.1-beta.33",
                                         py_version="0.5.8b2", npm_version="0.5.8-beta.2"))

    assert json.loads(release.PIN_FILE.read_text()) == {
        "tag": "v156.0.1-beta.33", "repo": "daijro/camoufox", "repo_name": "Official",
        "version": "156.0.1", "build": "beta.33",
    }
    assert 'version = "0.5.8b2"' in release.PYPROJECT.read_text()
    assert json.loads(release.PACKAGE_JSON.read_text())["version"] == "0.5.8-beta.2"
    assert 'LIBRARY_VERSION = "0.5.8-beta.2"' in release.TS_VERSION.read_text()


def test_the_pin_and_the_launchers_agree_on_its_format(tmp_path, monkeypatch):
    """What stamp writes is what pythonlib's loader reads."""
    import sys

    sys.path.insert(0, str(release.REPO_ROOT / "pythonlib"))
    from camoufox.browser_pin import load_pin

    monkeypatch.setattr(release, "PIN_FILE", tmp_path / "browser-pin.json")
    for name in ("PYPROJECT", "PACKAGE_JSON", "TS_VERSION"):
        dst = tmp_path / getattr(release, name).name
        shutil.copy(getattr(release, name), dst)
        monkeypatch.setattr(release, name, dst)
    release.cmd_stamp(argparse.Namespace(browser_tag="v156.0.1-beta.33",
                                         py_version="0.5.8", npm_version="0.5.8"))
    pin = load_pin(release.PIN_FILE)
    assert (pin.repo_name, pin.version, pin.build, pin.tag) == \
        ("official", "156.0.1", "beta.33", "v156.0.1-beta.33")
