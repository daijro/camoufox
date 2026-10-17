"""A Windows identity on another host behaves as stock Windows Firefox does.

Each value the launcher sets here was measured on stock Firefox on Windows
against this build on a Linux host claiming Windows. On a Windows host the
build already behaves that way, and a macOS or Linux identity is left as it is.
"""

import pytest

from camoufox import utils

from test_launch_environment import isolated_launch_dependencies  # noqa: F401

WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:156.0) Gecko/20100101 Firefox/156.0"
LIN_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) Gecko/20100101 Firefox/156.0"


@pytest.fixture
def launch(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    """launch_options on a Linux host; returns (config, prefs)."""
    monkeypatch.setattr(utils, "_host_os_key", lambda: "lin")
    seen = {}

    def capture(config, *args, **kwargs):
        seen["config"] = dict(config)
        return {}

    monkeypatch.setattr(utils, "get_env_vars", capture)

    def run(ua, **kwargs):
        config = {"navigator.userAgent": ua, **kwargs.pop("config", {})}
        prefs = utils.launch_options(config=config, i_know_what_im_doing=True, **kwargs)["firefox_user_prefs"]
        return seen["config"], prefs

    return run


def test_windows_identity_gets_windows_crt_math(launch):
    _, prefs = launch(WIN_UA)
    assert prefs["javascript.options.use_ucrt_math"] is True


@pytest.mark.parametrize("ua", [MAC_UA, LIN_UA])
def test_other_identities_keep_host_math(launch, ua):
    _, prefs = launch(ua)
    assert "javascript.options.use_ucrt_math" not in prefs


def test_windows_identity_on_windows_host_is_left_alone(launch, monkeypatch):
    monkeypatch.setattr(utils, "_host_os_key", lambda: "win")
    _, prefs = launch(WIN_UA)
    assert "javascript.options.use_ucrt_math" not in prefs


def test_caller_values_win(launch):
    _, prefs = launch(WIN_UA, firefox_user_prefs={"javascript.options.use_ucrt_math": False})
    assert prefs["javascript.options.use_ucrt_math"] is False


def test_windows_identity_gets_windows_keyboard(launch):
    config, _ = launch(WIN_UA)
    assert config["input:windowsKeyboard"] is True


@pytest.mark.parametrize("ua", [MAC_UA, LIN_UA])
def test_other_identities_keep_host_keyboard(launch, ua):
    config, _ = launch(ua)
    assert "input:windowsKeyboard" not in config


def test_windows_keyboard_on_windows_host_is_left_alone(launch, monkeypatch):
    monkeypatch.setattr(utils, "_host_os_key", lambda: "win")
    config, _ = launch(WIN_UA)
    assert "input:windowsKeyboard" not in config


def test_caller_keyboard_wins(launch):
    config, _ = launch(WIN_UA, config={"input:windowsKeyboard": False})
    assert config["input:windowsKeyboard"] is False
