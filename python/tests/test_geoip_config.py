"""The CLI over camoucore's GeoIP source choice. camoucore's tests cover the choice itself."""

import pytest
from yaml import safe_dump

from camoucore import geolocation

DEFAULT = "GeoIP AIO by daijro"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(geolocation, "GEOIP_DIR", tmp_path)
    monkeypatch.setattr(geolocation, "MMDB_DIR", tmp_path / "mmdb")
    monkeypatch.setattr(geolocation, "GEOIP_CONFIG", tmp_path / "config.yml")
    return tmp_path


def _saved(cache, **fields):
    (cache / "config.yml").write_text(safe_dump(fields))


def test_an_explicit_source_missing_from_the_list_can_be_replaced_from_the_cli(cache, monkeypatch):
    from camoufox import __main__ as cli

    _saved(cache, name="Gone", explicit=True)
    monkeypatch.setattr(cli, "_inquirer_select", lambda choices, message: dict(choices)[DEFAULT])
    cli._select_geoip_source()
    assert geolocation.load_geoip_config()["name"] == DEFAULT


def test_the_cli_reports_an_explicit_source_missing_from_the_list(cache, monkeypatch, capsys):
    from click.testing import CliRunner

    from camoufox import __main__ as cli

    _saved(cache, name="Gone", explicit=True)
    monkeypatch.setattr(cli, "ALLOW_GEOIP", True)
    monkeypatch.setattr(cli, "GEOIP_DIR", cache)
    monkeypatch.setattr(cli, "print_tree", lambda **_: None)

    info = cli.VersionInfo()
    info.geoip()
    info.console.print(info.t)
    assert "'Gone' not found" in " ".join(capsys.readouterr().out.split())

    result = CliRunner().invoke(cli.cli, ["list"])
    assert result.exit_code == 0, result.output
    assert "'Gone' not found" in result.output
