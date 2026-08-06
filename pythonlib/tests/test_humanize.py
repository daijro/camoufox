"""Regression tests for humanized cursor launch configuration."""

import pytest

from camoufox import utils


@pytest.fixture
def captured_launch_config(monkeypatch):
    captured = {}

    monkeypatch.setattr(utils, "generate_fingerprint", lambda **_kwargs: object())
    monkeypatch.setattr(utils, "from_browserforge", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(utils, "get_screen_cons", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        utils, "_generate_random_font_subset", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        utils, "_generate_random_voice_subset", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(utils, "validate_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(utils, "add_default_addons", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(utils, "fix_navigator_arch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        utils, "fix_screen_no_taskbar", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        utils, "clamp_window_dimensions", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(utils, "installed_verstr", lambda *_args, **_kwargs: "152.0")
    monkeypatch.setattr(utils, "launch_path", lambda *_args, **_kwargs: "/camoufox")
    monkeypatch.setattr(utils.LeakWarning, "warn", lambda *_args, **_kwargs: None)

    def capture_env(config, _target_os):
        captured.clear()
        captured.update(config)
        return {}

    monkeypatch.setattr(utils, "get_env_vars", capture_env)

    def launch(humanize):
        utils.launch_options(
            humanize=humanize,
            block_webgl=True,
            i_know_what_im_doing=True,
        )
        return captured.copy()

    return launch


def test_humanize_true_does_not_set_boolean_duration(captured_launch_config) -> None:
    config = captured_launch_config(True)

    assert config["humanize"] is True
    assert "humanize:maxTime" not in config


@pytest.mark.parametrize("duration", [1, 5, 1.25])
def test_humanize_duration_is_encoded_as_double(
    captured_launch_config, duration
) -> None:
    config = captured_launch_config(duration)

    assert config["humanize"] is True
    assert config["humanize:maxTime"] == float(duration)
    assert type(config["humanize:maxTime"]) is float
