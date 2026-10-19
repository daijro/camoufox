"""A caller's own binary is never replaced -- but it should still be checked.

A managed install below the floor gets upgraded by pkgman. `executable_path`
deliberately bypasses that, which leaves one pairing nothing checks: an old
build driven by Playwright >= 1.61, whose viewport fields the older Juggler
schema rejects. Without this the user sees a bare "Protocol error
(Browser.setDefaultViewport)" and nothing naming the cause.

It warns rather than raises on purpose: camoufox defaults to no_viewport when
it spoofs window dimensions, so the default path works on an old build. Only an
explicit viewport breaks, so refusing to launch would break working setups.
"""

import json

import pytest

from camoufox import pkgman, utils


def _bundle(tmp_path, build):
    """A browser directory with version.json beside the binary, as a release has."""
    d = tmp_path / f"152.0.4-{build}"
    d.mkdir()
    (d / "version.json").write_text(json.dumps({"version": "152.0.4", "build": build}))
    return d / "camoufox-bin"


@pytest.fixture
def floor_at_beta30(monkeypatch):
    monkeypatch.setattr(utils, "effective_version_min", lambda: pkgman.Version(build="beta.30"))


def test_warns_when_the_supplied_build_is_too_old(tmp_path, floor_at_beta30):
    exe = _bundle(tmp_path, "beta.29")

    with pytest.warns(RuntimeWarning, match=r"beta\.29.*beta\.30"):
        utils.warn_if_executable_predates_playwright(exe)


def test_names_the_symptom_the_user_will_actually_see(tmp_path, floor_at_beta30):
    exe = _bundle(tmp_path, "beta.29")

    with pytest.warns(RuntimeWarning) as caught:
        utils.warn_if_executable_predates_playwright(exe)

    assert "Browser.setDefaultViewport" in str(caught[0].message)


@pytest.mark.parametrize("build", ["beta.30", "beta.31"])
def test_silent_when_the_build_is_new_enough(tmp_path, floor_at_beta30, build, recwarn):
    utils.warn_if_executable_predates_playwright(_bundle(tmp_path, build))

    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


def test_silent_for_a_custom_build_with_no_version_json(tmp_path, floor_at_beta30, recwarn):
    """An unpackaged objdir build tells us nothing; do not nag about it."""
    (tmp_path / "dist").mkdir()

    utils.warn_if_executable_predates_playwright(tmp_path / "dist" / "camoufox-bin")

    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


def test_silent_when_no_executable_path_was_given(floor_at_beta30, recwarn):
    utils.warn_if_executable_predates_playwright(None)

    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]
