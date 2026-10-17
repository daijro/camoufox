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


def test_windows_identity_gets_windows_behaviour(launch):
    _, prefs = launch(WIN_UA)
    for pref, value in utils.WINDOWS_BEHAVIOUR_PREFS.items():
        assert prefs[pref] == value
    # Spot checks against stock Firefox on Windows, so an edit to the table
    # cannot quietly agree with itself.
    assert prefs["media.eme.enabled"] is True
    assert prefs["middlemouse.paste"] is False
    assert prefs["general.autoScroll"] is True
    assert prefs["layout.word_select.eat_space_to_next_word"] is True
    assert prefs["full-screen-api.transition-duration.enter"] == "200 200"


@pytest.mark.parametrize("ua", [MAC_UA, LIN_UA])
def test_other_identities_keep_host_behaviour(launch, ua):
    _, prefs = launch(ua)
    assert not set(utils.WINDOWS_BEHAVIOUR_PREFS) & set(prefs)


def test_windows_behaviour_on_windows_host_is_left_alone(launch, monkeypatch):
    monkeypatch.setattr(utils, "_host_os_key", lambda: "win")
    _, prefs = launch(WIN_UA)
    assert not set(utils.WINDOWS_BEHAVIOUR_PREFS) & set(prefs)


def test_caller_behaviour_wins(launch):
    _, prefs = launch(WIN_UA, firefox_user_prefs={"middlemouse.paste": True})
    assert prefs["middlemouse.paste"] is True


# Scrollbars are drawn by the host build's theme: GTK's are 12 px where stock
# Windows measures 17 (classic, ui.useOverlayScrollbars 0), so a Windows 10
# identity on a Linux host showed a 12 px gutter.
SCROLLBAR_STYLE = "widget.non-native-theme.scrollbar.style"


@pytest.mark.parametrize(
    "overlay, style",
    [pytest.param(0, 4, id="windows-10-classic"), pytest.param(1, 5, id="windows-11-overlay")],
)
def test_windows_identity_draws_windows_scrollbars(launch, overlay, style):
    _, prefs = launch(WIN_UA, firefox_user_prefs={"ui.useOverlayScrollbars": overlay})
    assert prefs[SCROLLBAR_STYLE] == style
    assert prefs["widget.non-native-theme.win.scrollbar.use-system-size"] is False


@pytest.mark.parametrize("ua", [MAC_UA, LIN_UA])
def test_other_identities_keep_host_scrollbars(launch, ua):
    _, prefs = launch(ua)
    assert SCROLLBAR_STYLE not in prefs


def test_scrollbars_on_a_windows_host_are_left_alone(launch, monkeypatch):
    monkeypatch.setattr(utils, "_host_os_key", lambda: "win")
    _, prefs = launch(WIN_UA)
    assert SCROLLBAR_STYLE not in prefs


def test_caller_scrollbar_style_wins(launch):
    _, prefs = launch(WIN_UA, firefox_user_prefs={SCROLLBAR_STYLE: 2})
    assert prefs[SCROLLBAR_STYLE] == 2
