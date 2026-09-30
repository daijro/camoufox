"""The release plan: which versions a merge or a tag publishes, and which browser they pair with."""

import argparse
import json
import re
import shutil

import pytest
import yaml

from ci import browser_inputs, release
from ci._util import read_upstream_sh
from ci.release import (
    is_gate_check,
    last_library_tag,
    library_changed,
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


def _released(tag, digest, **extra):
    return {"tag_name": tag, "manifest": release.manifest(tag, digest, "0" * 40), **extra}


def test_a_library_pairs_with_the_newest_non_draft_release_from_its_sources():
    releases = [
        _released("v156.0.1-beta.35", "aaa", draft=True),
        _released("v156.0.1-beta.34", "bbb"),
        _released("v156.0.1-beta.33", "aaa"),
        {"tag_name": "v152.0.4-beta.31", "assets": []},  # before manifests
    ]
    assert paired_release(releases, "aaa")["tag_name"] == "v156.0.1-beta.33"
    assert paired_release(releases, "ccc") is None


def test_a_release_without_a_manifest_asset_is_not_downloaded(monkeypatch):
    monkeypatch.setattr(release, "http_json", lambda url: pytest.fail(f"fetched {url}"))
    assert release.release_manifest({"tag_name": "v152.0.4-beta.30", "assets": [{"name": "a.zip"}]}) is None


def test_library_tags_order_as_versions_and_never_as_browser_tags():
    tags = ["v0.5.7b1", "v0.5.7b10", "v0.5.7b2", "v0.5.6", "v156.0.1-beta.33", "font-bundle-v1"]
    assert last_library_tag(tags) == "v0.5.7b10"
    assert last_library_tag(tags + ["v0.5.7"]) == "v0.5.7"
    assert last_library_tag(["v156.0.1-beta.33"]) is None
    # a library prerelease tag must not take a browser release number
    assert next_browser_release("beta.32", ["v0.5.7b40"]) == "beta.32"


def test_the_gate_check_is_found_when_release_yml_runs_the_tests():
    assert is_gate_check("All tests passed")
    assert is_gate_check("tests / All tests passed")
    assert not is_gate_check("Not All tests passed")


def _git(repo, *args):
    import subprocess

    return subprocess.run(["git", "-c", "user.email=ci@test", "-c", "user.name=ci", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def library_repo(tmp_path):
    """A repo whose last library release, v0.5.7b1, is tagged on HEAD."""
    for rel in ("pythonlib/camoufox/a.py", "docs/a.md", "patches/a.patch", "upstream.sh"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("a\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "released")
    _git(tmp_path, "tag", "v0.5.7b1")
    return tmp_path


@pytest.mark.parametrize("changed, publish", [
    ("docs/a.md", False),
    ("pythonlib/camoufox/a.py", True),
    ("patches/a.patch", True),  # a new browser means a new pin
])
def test_a_library_prerelease_is_published_only_when_what_it_ships_changed(library_repo, changed, publish):
    (library_repo / changed).write_text("b\n")
    _git(library_repo, "commit", "-qam", "change")
    assert library_changed(library_repo)[0] is publish


def test_the_first_library_prerelease_is_always_published(library_repo):
    _git(library_repo, "tag", "-d", "v0.5.7b1")
    assert library_changed(library_repo)[0] is True


def test_set_build_names_the_tags_release_in_the_working_tree_only(tmp_path, monkeypatch):
    shutil.copy(release.REPO_ROOT / "upstream.sh", tmp_path / "upstream.sh")
    monkeypatch.setattr(release, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(release, "read_upstream_sh",
                        lambda: read_upstream_sh(tmp_path / "upstream.sh"))
    version = read_upstream_sh(tmp_path / "upstream.sh")["version"]

    release.cmd_set_build(argparse.Namespace(tag=f"v{version}-beta.77"))
    assert re.search(r"^release=beta\.77$", (tmp_path / "upstream.sh").read_text(), re.M)
    with pytest.raises(SystemExit):
        release.cmd_set_build(argparse.Namespace(tag="v1.0-beta.78"))  # another Firefox


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


# The jobs each channel skips by design, and the jobs it must reach.
CHANNELS = {
    "prerelease": ({"promote-browser"},
                   {"build-browser", "publish-browser", "build-library", "publish-pypi",
                    "publish-npm", "tag-library"}),
    "stable": ({"tests", "build-browser", "publish-browser", "tag-library"},
               {"plan", "build-library", "promote-browser", "publish-pypi", "publish-npm"}),
}


@pytest.mark.parametrize("channel", CHANNELS)
def test_no_job_a_channel_needs_is_skipped_by_a_job_it_skips(channel):
    """A job whose `if` has no status function gets an implicit success(), which
    is false when any job upstream of it -- not only its direct needs -- was
    skipped. The first prerelease published to PyPI and skipped npm that way:
    promote-browser, skipped on every push, sits upstream of publish-npm."""
    jobs = yaml.safe_load((release.REPO_ROOT / ".github/workflows/release.yml")
                          .read_text(encoding="utf-8"))["jobs"]

    def needs(name):
        n = jobs[name].get("needs", [])
        return [n] if isinstance(n, str) else n

    def upstream(name):
        seen = set()
        stack = list(needs(name))
        while stack:
            job = stack.pop()
            if job not in seen:
                seen.add(job)
                stack.extend(needs(job))
        return seen

    skipped, required = CHANNELS[channel]
    unguarded = [
        name for name in sorted(required)
        if upstream(name) & skipped
        and not re.search(r"!cancelled\(\)|always\(\)", str(jobs[name].get("if", "")))
    ]
    assert not unguarded, f"{channel}: skipped by an upstream job it does not need: {unguarded}"


def test_npm_publish_is_given_a_local_path():
    """npm reads `dir/file.tgz` as a GitHub owner/repo and tries to clone it; the
    first npm publish failed that way. A local tarball needs `./` or `/`."""
    jobs = yaml.safe_load((release.REPO_ROOT / ".github/workflows/release.yml")
                          .read_text(encoding="utf-8"))["jobs"]
    runs = [step["run"] for job in jobs.values() for step in job.get("steps", [])
            if "npm publish" in step.get("run", "")]
    assert runs
    for run in runs:
        target = re.search(r"npm publish\s+(\S+)", run).group(1)
        assert target.startswith(("./", "/")), f"not a local path to npm: {target}"


def _wheel(tmp_path, version, body=b"print('hi')\n"):
    import zipfile

    path = tmp_path / f"camoufox-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("camoufox/__init__.py", body)
        z.writestr(f"camoufox-{version}.dist-info/METADATA", f"Name: camoufox\nVersion: {version}\n")
        z.writestr(f"camoufox-{version}.dist-info/RECORD", f"camoufox/__init__.py,sha256={version}\n")
    return path


def _tarball(tmp_path, version, body=b"export {};\n"):
    import io
    import tarfile

    path = tmp_path / f"camoufox-camoufox-{version}.tgz"
    with tarfile.open(path, "w:gz") as t:
        for name, data in {"package/package.json": f'{{"version": "{version}"}}'.encode(),
                           "package/dist/index.js": body}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return path


def test_the_newest_published_version_orders_prereleases_below_their_release():
    assert release.newest_version(["0.5.6", "0.5.7b1", "0.5.7b10", "0.5.7b2"], release._PY_VERSION) == "0.5.7b10"
    assert release.newest_version(["0.5.7b3", "0.5.7"], release._PY_VERSION) == "0.5.7"
    assert release.newest_version(["0.5.6", "0.5.7-beta.2", "0.1.19"], release._NPM_VERSION) == "0.5.7-beta.2"
    assert release.newest_version([], release._NPM_VERSION) is None


@pytest.mark.parametrize("build", [_wheel, _tarball])
def test_a_package_that_differs_only_in_its_version_is_not_new(tmp_path, build):
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    old = build(tmp_path / "old", "0.5.7b2" if build is _wheel else "0.5.7-beta.2")
    new = build(tmp_path / "new", "0.5.7b3" if build is _wheel else "0.5.7-beta.3")
    changed = build(tmp_path / "new", "0.5.7b4" if build is _wheel else "0.5.7-beta.4", body=b"changed\n")
    spelling = release._PY_VERSION if build is _wheel else release._NPM_VERSION
    published = ["0.5.6", "0.5.7b2"] if build is _wheel else ["0.5.6", "0.5.7-beta.2"]

    def fetch(version, dest):
        assert version == published[-1], "compared with the newest published version"
        return old

    ver = lambda p: p.name.split("-")[1] if build is _wheel else p.name[len("camoufox-camoufox-"):-4]  # noqa: E731
    assert release.changed_since_published(new, ver(new), published, spelling, fetch, "x")[0] is False
    is_new, why = release.changed_since_published(changed, ver(changed), published, spelling, fetch, "x")
    assert is_new and ("__init__.py" in why or "index.js" in why), why
    assert release.changed_since_published(new, ver(new), [], spelling, fetch, "x")[0] is True


def test_each_registry_is_published_only_when_its_own_package_changed():
    jobs = yaml.safe_load((release.REPO_ROOT / ".github/workflows/release.yml")
                          .read_text(encoding="utf-8"))["jobs"]
    assert "outputs.publish_pypi == 'true'" in jobs["publish-pypi"]["if"]
    assert "outputs.publish_npm == 'true'" in jobs["publish-npm"]["if"]
    # npm must not depend on PyPI having published: a TypeScript-only change skips PyPI.
    assert "needs.publish-pypi.result == 'skipped'" in jobs["publish-npm"]["if"]
    steps = jobs["build-library"]["steps"]
    assert any("ci.release lib-diff" in s.get("run", "") for s in steps)
