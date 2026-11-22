"""Humanize launch configuration: myuri(), with the parts it is passed, or raw()
per channel, run by the driver. Nothing of it reaches the browser's config."""


import pytest

from camoufox import utils
from camoufox.humanize import CHANNELS, cursory, myuri, normalize, raw


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
        True,
        {},
        {"mouse": raw()},
        {"mouse": myuri(move=noop), "keyboard": myuri(type=noop), "scroll": myuri(wheel=noop), "seed": 9,
         "settings": {"typing": {"wpm": 70}}},
        {"keyboard": raw(), "seed": 2**32 - 1},
    ],
)
def test_no_humanize_key_reaches_the_browser(captured_launch_config, humanize) -> None:
    config = captured_launch_config(humanize)
    assert not [key for key in config if key.startswith("humanize")]


def test_no_humanize_is_raw_and_humanize_is_myuri() -> None:
    for off in (None, False):
        assert normalize(off) == ({channel: raw() for channel in CHANNELS}, None, {})
    assert normalize(True) == ({channel: myuri() for channel in CHANNELS}, None, {})
    engines, seed, settings = normalize({"scroll": myuri(into_view=noop), "keyboard": {"engine": "myuri", "options": {}},
                                         "seed": 5, "settings": {"typing": {"wpm": 70}}})
    assert engines["mouse"] == myuri() and engines["keyboard"] == myuri()
    assert engines["scroll"] == myuri(into_view=noop)
    assert seed == 5 and settings == {"typing": {"wpm": 70}}


def test_cursory_is_myuri() -> None:
    assert cursory() == myuri() and cursory(move=noop) == myuri(move=noop)
    engines = normalize({"mouse": {"engine": "cursory", "options": {"move": noop}}, "scroll": cursory()}).engines
    assert engines == {"mouse": myuri(move=noop), "keyboard": myuri(), "scroll": myuri()}


@pytest.mark.parametrize(
    "humanize",
    [1.5, 2, {"mouse": "cursory"}, {"mouse": {"engine": "auto", "options": {}}}],
)
def test_in_browser_humanization_is_refused(humanize) -> None:
    with pytest.raises(ValueError, match="the browser does not humanize input"):
        normalize(humanize)


@pytest.mark.parametrize(
    "humanize, message",
    [
        ({"touch": raw()}, "no channel"),
        ({"seed": -1}, "seed"),
        ({"seed": 2**32}, "seed"),
        ({"seed": True}, "seed"),
        ({"seed": "1"}, "seed"),
        ({"mouse": 3}, "is not an engine"),
        ({"mouse": {"engine": "myuri", "options": {"speed": 1}}}, r"myuri\(\) has no part 'speed'"),
        ({"mouse": {"engine": "cursory", "options": {"maxTime": 1}}}, r"myuri\(\) has no part 'maxTime'"),
        ({"mouse": myuri(type=noop)}, r'humanize\["mouse"\]: myuri\(type=...\) is not a mouse part'),
        ({"keyboard": {"engine": "myuri", "options": {"wpm": 70}}}, r"myuri\(\) has no part 'wpm'.*humanize\[\"settings\"\]"),
        ({"settings": 70}, r'humanize\["settings"\] must be a dict'),
        ({"settings": {"typing": {"speed": 70}}}, r"humanize\[\"settings\"\]: myuri: unknown settings key 'speed'"),
        ({"keyboard": {"engine": "myuri", "options": {"type": "fast"}}}, "takes the function that replaces the part"),
        ({"mouse": {"engine": "custom", "fn": noop}}, "is not an engine"),
        ({"mouse": {"engine": "raw", "options": {"speed": 1}}}, "takes no options"),
    ],
)
def test_malformed_settings_are_refused(humanize, message) -> None:
    with pytest.raises(ValueError, match=message):
        normalize(humanize)


def test_launch_options_refuses_in_browser_humanization(captured_launch_config) -> None:
    with pytest.raises(ValueError, match="the browser does not humanize input"):
        captured_launch_config(1.5)
