"""Humanize launch configuration: raw() or custom(fn) per channel, run by the
driver. Nothing of it reaches the browser's config."""

import json

import pytest

from camoufox import utils
from camoufox.humanize import CHANNELS, custom, normalize, raw


def noop(*_args, **_kwargs):
    return None


@pytest.fixture
def captured_launch_config(monkeypatch):
    captured = {}

    monkeypatch.setattr(utils, "generate_fingerprint", lambda **_kwargs: object())
    monkeypatch.setattr(utils, "from_fpgen", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(utils, "get_screen_cons", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        utils, "_generate_random_font_subset", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(
        utils, "draw_voice_config", lambda *_args, **_kwargs: {"voices": []}
    )
    monkeypatch.setattr(utils, "validate_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(utils, "add_default_addons", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(utils, "fix_navigator_arch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        utils, "follow_baseline_protection", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        utils, "clamp_window_dimensions", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(utils, "installed_verstr", lambda *_args, **_kwargs: "152.0")
    monkeypatch.setattr(utils, "launch_path", lambda *_args, **_kwargs: "/camoufox")
    monkeypatch.setattr(utils.LeakWarning, "warn", lambda *_args, **_kwargs: None)

    def capture_env(config, _target_os, **_kwargs):
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


@pytest.mark.parametrize(
    "humanize",
    [
        None,
        False,
        {},
        {"mouse": raw()},
        {"mouse": custom(noop), "keyboard": custom(noop), "scroll": custom(noop), "seed": 9},
        {"keyboard": "raw", "seed": 2**64 - 1},
    ],
)
def test_no_humanize_key_reaches_the_browser(captured_launch_config, humanize) -> None:
    config = captured_launch_config(humanize)
    assert not [key for key in config if key.startswith("humanize")]


def test_normalize_defaults_every_channel_to_raw() -> None:
    engines, seed = normalize(None)
    assert engines == {channel: raw() for channel in CHANNELS} and seed is None
    engines, seed = normalize({"scroll": custom(noop), "seed": 5})
    assert engines["mouse"] == raw() and engines["keyboard"] == raw()
    assert engines["scroll"]["engine"] == "custom" and engines["scroll"]["fn"] is noop
    assert seed == 5


@pytest.mark.parametrize(
    "humanize",
    [True, 1.5, 2, {"mouse": "cursory"}, {"mouse": {"engine": "auto", "options": {}}},
     {"scroll": {"engine": "cursory", "options": {"maxTime": 1}}}],
)
def test_in_browser_humanization_is_refused(humanize) -> None:
    with pytest.raises(ValueError, match="no longer humanizes"):
        normalize(humanize)


@pytest.mark.parametrize(
    "humanize, message",
    [
        ({"touch": raw()}, "no channel"),
        ({"seed": -1}, "seed"),
        ({"seed": 2**64}, "seed"),
        ({"seed": True}, "seed"),
        ({"seed": "1"}, "seed"),
        ({"mouse": 3}, "must be raw\\(\\) or custom"),
        ({"mouse": "custom"}, "needs its function"),
        ({"mouse": {**custom(noop), "options": {"speed": 1}}}, "takes no options"),
        ({"mouse": {"engine": "raw", "options": {"speed": 1}}}, "takes no options"),
    ],
)
def test_malformed_settings_are_refused(humanize, message) -> None:
    with pytest.raises(ValueError, match=message):
        normalize(humanize)


def test_raw_is_plain_data() -> None:
    assert raw() == {"engine": "raw", "options": {}}
    assert json.loads(json.dumps(raw())) == raw()


def test_custom_needs_a_function() -> None:
    with pytest.raises(ValueError, match="takes the function"):
        custom("not callable")


def test_launch_options_refuses_in_browser_humanization(captured_launch_config) -> None:
    with pytest.raises(ValueError, match="no longer humanizes"):
        captured_launch_config(True)
