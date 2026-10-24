"""`camoufox fetch` installs a named build with one GitHub API call, and fails loudly.

A fetch that names its build, explicitly or through the release's browser pin,
reads that build's release by tag instead of syncing every repository first.
The sync spent a request per source on every fetch, which exhausted the
unauthenticated API quota on shared CI runners, and it reads only the newest
page of releases, so an older build could not be found at all (#919). Every
fetch that installs nothing exits non-zero, so CI stops at the step that failed.
"""

import json

import pytest
import requests
from click.testing import CliRunner

from camoufox import __main__ as cli
from camoufox import browser_pin, multiversion, pkgman
from camoufox.__version__ import CONSTRAINTS

API = "https://api.github.com/repos/daijro/camoufox/releases"
UPDATE = cli.CamoufoxUpdate


@pytest.fixture
def github(monkeypatch):
    """Serve URLs from a dict (anything else is a 404), and record every request."""
    served, requested = {}, []

    class Response:
        def __init__(self, url):
            self.url = url
            self.status_code = 200 if url in served else 404

        def raise_for_status(self):
            if self.status_code != 200:
                raise requests.HTTPError(f"404 Client Error: Not Found for url: {self.url}", response=self)

        def json(self):
            return served[self.url]

    def get(url, **_kwargs):
        requested.append(url)
        return Response(url)

    monkeypatch.setattr(pkgman.requests, "get", get)
    monkeypatch.setattr(pkgman, "_release_interfaces", {})
    monkeypatch.setattr(pkgman, "OS_NAME", "lin")
    monkeypatch.setattr(pkgman.RepoConfig, "get_arch", lambda self, spoof_arch=None: spoof_arch or "x86_64")
    return served, requested


@pytest.fixture
def installs(tmp_path, monkeypatch):
    """Record what fetch would install, with an empty cache and no pin."""
    installed = []

    class Update:
        def __init__(self, repo_config=None, selected_version=None):
            self.repo_config, self.selected = repo_config, selected_version

        def update(self, replace=False, i_know_what_im_doing=False):
            installed.append((self.repo_config.name, self.selected.version.full_string, i_know_what_im_doing))

    monkeypatch.setattr(cli, "CamoufoxUpdate", Update)
    for name in ("remove_incompatible_data", "maybe_download_addons", "ensure_fpgen_model", "download_mmdb"):
        monkeypatch.setattr(cli, name, lambda *a, **k: None)
    monkeypatch.setattr(multiversion, "REPO_CACHE_FILE", tmp_path / "repo_cache.json")
    monkeypatch.setattr(multiversion, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(browser_pin, "PIN_FILE", tmp_path / "browser-pin.json")
    return installed


def _release(served, tag, build, version="156.0.1", prerelease=False):
    manifest = f"https://example.invalid/{tag}/manifest.json"
    served[manifest] = {"interface": CONSTRAINTS.INTERFACE}
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "assets": [
            {"name": f"camoufox-{version}-{build}-lin.x86_64.zip",
             "browser_download_url": f"https://example.invalid/{tag}/browser.zip",
             "digest": "sha256:" + "ab" * 32,
             "created_at": "2026-10-01T00:00:00Z"},
            {"name": "manifest.json", "id": tag, "browser_download_url": manifest},
        ],
    }


def _api_requests(requested):
    return [url for url in requested if url.startswith("https://api.github.com/")]


def test_a_named_build_is_fetched_with_one_api_call(github, installs):
    served, requested = github
    served[f"{API}/tags/v156.0.1-beta.33"] = _release(served, "v156.0.1-beta.33", "beta.33")

    result = CliRunner().invoke(cli.cli, ["fetch", "official/156.0.1-beta.33"])

    assert result.exit_code == 0, result.output
    assert _api_requests(requested) == [f"{API}/tags/v156.0.1-beta.33"]
    assert installs == [("Official", "156.0.1-beta.33", False)]


def test_the_paired_build_is_fetched_with_one_api_call(github, installs, tmp_path):
    served, requested = github
    (tmp_path / "browser-pin.json").write_text(json.dumps({
        "tag": "v156.0.1-beta.33", "repo": "daijro/camoufox", "repo_name": "Official",
        "version": "156.0.1", "build": "beta.33",
    }))
    served[f"{API}/tags/v156.0.1-beta.33"] = _release(served, "v156.0.1-beta.33", "beta.33", prerelease=True)

    result = CliRunner().invoke(cli.cli, ["fetch"])

    assert result.exit_code == 0, result.output
    assert _api_requests(requested) == [f"{API}/tags/v156.0.1-beta.33"]
    assert installs == [("Official", "156.0.1-beta.33", True)]


def test_a_build_without_its_own_tag_is_found_by_syncing(github, installs, monkeypatch):
    """Early alphas were published under other tags (v146-hardware holds 146.0.1-alpha.25)."""
    served, requested = github
    official = pkgman.RepoConfig.get_default()
    monkeypatch.setattr(pkgman.RepoConfig, "load_repos", staticmethod(lambda: [official]))
    served[API] = [_release(served, "v146-hardware", "alpha.25", version="146.0.1")]

    result = CliRunner().invoke(cli.cli, ["fetch", "official/146.0.1-alpha.25"])

    assert result.exit_code == 0, result.output
    assert installs == [("Official", "146.0.1-alpha.25", False)]


def test_a_build_that_does_not_exist_fails_the_fetch(github, installs, monkeypatch):
    served, _ = github
    official = pkgman.RepoConfig.get_default()
    monkeypatch.setattr(pkgman.RepoConfig, "load_repos", staticmethod(lambda: [official]))
    served[API] = []

    result = CliRunner().invoke(cli.cli, ["fetch", "official/156.0.1-beta.99"])

    assert result.exit_code != 0
    assert "not found" in result.output
    assert installs == []


def test_a_failed_install_fails_the_fetch(github, installs, monkeypatch):
    served, _ = github
    served[f"{API}/tags/v156.0.1-beta.33"] = _release(served, "v156.0.1-beta.33", "beta.33")

    def broken(self, replace=False, i_know_what_im_doing=False):
        raise requests.HTTPError("404 Client Error: Not Found for url: https://example.invalid/browser.zip")

    monkeypatch.setattr(cli.CamoufoxUpdate, "update", broken)

    result = CliRunner().invoke(cli.cli, ["fetch", "official/156.0.1-beta.33"])

    assert result.exit_code != 0
    assert "Release not found (404)" in result.output


def test_a_rate_limited_lookup_fails_the_fetch(github, installs, monkeypatch):
    served, _ = github
    official = pkgman.RepoConfig.get_default()
    monkeypatch.setattr(pkgman.RepoConfig, "load_repos", staticmethod(lambda: [official]))

    def limited(url, **_kwargs):
        response = requests.Response()
        response.status_code, response.url = 403, url
        response.reason = "rate limit exceeded"
        return response

    monkeypatch.setattr(pkgman.requests, "get", limited)

    result = CliRunner().invoke(cli.cli, ["fetch", "official/156.0.1-beta.33"])

    assert result.exit_code != 0
    assert "403" in result.output
    assert installs == []


def test_an_unconfirmed_prerelease_fails_the_fetch(github, installs, monkeypatch):
    """CI has no terminal to answer the prerelease prompt; the fetch must not pass."""
    served, _ = github
    served[f"{API}/tags/v158.0-beta.40"] = _release(served, "v158.0-beta.40", "beta.40", version="158.0", prerelease=True)
    monkeypatch.setattr(cli, "CamoufoxUpdate", UPDATE)
    monkeypatch.setattr(cli, "installed_verstr", lambda: None)
    monkeypatch.setattr(pkgman.CamoufoxFetcher, "install", lambda self, replace=False: installs.append(self.verstr))

    result = CliRunner().invoke(cli.cli, ["fetch", "official/158.0-beta.40"], input="")

    assert result.exit_code != 0
    assert "Installation cancelled." in result.output
    assert installs == []
