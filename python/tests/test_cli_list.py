"""`camoufox list --path` shows install paths in both listing modes."""

from pathlib import Path

from click.testing import CliRunner

from camoufox import __main__ as cli
from camoufox.multiversion import InstalledVersion
from camoufox.pkgman import Version


def test_list_all_shows_the_path_of_an_installed_build(monkeypatch):
    install = Path("/cache/browsers/official/152.0.4-beta.30")
    installed = InstalledVersion(
        repo_name="official", version=Version(build="beta.30", version="152.0.4"), path=install
    )
    cache = {"repos": [{"name": "official", "versions": [{"version": "152.0.4", "build": "beta.30"}]}]}
    monkeypatch.setattr(cli, "_ensure_synced", lambda: True)
    monkeypatch.setattr(cli, "load_repo_cache", lambda: cache)
    monkeypatch.setattr(cli, "list_installed", lambda: [installed])

    result = CliRunner().invoke(cli.cli, ["list", "all", "--path"])

    assert result.exit_code == 0, result.output
    assert str(install) in result.output
