"""
launch_options() resolves the browser it will launch before reading its version.

It used to read the version of the active install first and resolve the binary
last. With nothing installed that raised CamoufoxNotInstalled ("run `camoufox
fetch`") before the download in camoufox_path() was ever reached (#835), while
the TypeScript launcher downloaded. With an outdated install it generated the
identity for the old Firefox version and then launched the upgraded one.
"""

import pytest

from camoufox import utils
from camoufox.exceptions import CamoufoxNotInstalled


@pytest.fixture
def nothing_installed(monkeypatch, tmp_path):
    """No active install; launch_path() is where the download happens."""
    def not_installed():
        raise CamoufoxNotInstalled("Official is not installed. Please run `camoufox fetch` to install.")

    binary = tmp_path / "camoufox-bin"
    downloads = []

    def launch_path(*_args, **_kwargs):
        downloads.append(True)
        (tmp_path / "application.ini").write_text("[App]\nVersion=157.0\n")
        return str(binary)

    seen = {}

    def from_fpgen(_fingerprint, ff_version, *_args, **_kwargs):
        seen["ff_version"] = ff_version
        return {}

    monkeypatch.setattr(utils, "installed_verstr", not_installed)
    monkeypatch.setattr(utils, "launch_path", launch_path)
    monkeypatch.setattr(utils, "generate_fingerprint", lambda *args, **kwargs: object())
    monkeypatch.setattr(utils, "from_fpgen", from_fpgen)
    for name in ("add_default_addons", "get_screen_cons", "fix_navigator_arch",
                 "fix_screen_no_taskbar", "clamp_window_dimensions",
                 "set_media_devices_defaults", "validate_config"):
        monkeypatch.setattr(utils, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "_generate_random_font_subset", lambda *args, **kwargs: [])
    monkeypatch.setattr(utils, "_generate_random_voice_subset", lambda *args, **kwargs: [])
    monkeypatch.setattr(utils, "get_env_vars", lambda *args, **kwargs: {})
    return downloads, seen, str(binary)


def test_a_first_launch_installs_instead_of_raising(nothing_installed):
    downloads, seen, binary = nothing_installed

    options = utils.launch_options(headless=True, i_know_what_im_doing=True)

    assert downloads
    assert options["executable_path"] == binary
    assert seen["ff_version"] == "157"
