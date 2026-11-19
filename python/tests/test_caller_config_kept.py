"""A value the caller passed is kept, and an incoherent one is warned about (#956).

coherence.py used to repair a config the caller wrote just as it repairs a
generated one, so an Apple Silicon identity passed with colorDepth 24 silently
launched with 30. The caller's value now stands, and a LeakWarning that
i_know_what_im_doing does not silence names the key and what it contradicts.
"""

import warnings

from camoufox import utils
from camoufox._warnings import LeakWarning

from test_launch_environment import isolated_launch_dependencies  # noqa: F401

MAC = {"navigator.userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:158.0) Gecko/20100101 Firefox/158.0",
       "navigator.platform": "MacIntel", "webGl:vendor": "Apple", "webGl:renderer": "Apple M1, or similar",
       "screen.width": 1512, "screen.height": 982}


def launch(monkeypatch, config):
    launched = {}
    monkeypatch.setattr(utils, "get_env_vars", lambda config_map, *args, **kwargs: launched.update(config_map) or {})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        utils.launch_options(os="macos", config=dict(config), i_know_what_im_doing=True, headless=True)
    return launched, [str(w.message) for w in caught if issubclass(w.category, LeakWarning)]


def incoherent(messages):
    return [m for m in messages if m.startswith("LEAK: config sets")]


def test_caller_colour_depth_is_kept_and_warned(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    launched, messages = launch(monkeypatch, {**MAC, "screen.colorDepth": 24})
    assert launched["screen.colorDepth"] == 24
    assert launched.get("screen.pixelDepth", 24) == 24
    assert any("screen.colorDepth" in m and "colorDepth 24" in m for m in incoherent(messages)), messages


def test_caller_device_pixel_ratio_is_kept_and_warned(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    launched, messages = launch(monkeypatch, {**MAC, "window.devicePixelRatio": 1.5})
    assert launched["window.devicePixelRatio"] == 1.5
    assert any("window.devicePixelRatio" in m for m in incoherent(messages)), messages


def test_caller_gpu_is_kept_and_warned(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    # An Intel Mac GPU behind a notched panel only Apple Silicon Macs have.
    intel = "Intel(R) HD Graphics 400, or similar"
    launched, messages = launch(monkeypatch, {**MAC, "webGl:vendor": "Intel Inc.", "webGl:renderer": intel})
    assert launched["webGl:renderer"] == intel
    assert any("webGl:renderer" in m for m in incoherent(messages)), messages


def test_coherent_caller_values_do_not_warn(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    launched, messages = launch(monkeypatch, {**MAC, "screen.colorDepth": 30, "screen.pixelDepth": 30,
                                              "window.devicePixelRatio": 2})
    assert launched["screen.colorDepth"] == 30
    assert not incoherent(messages), messages


def test_drawn_mac_colour_depth_is_30(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    # A drawn Intel Mac at 24 bits: not the caller's, so it is repaired. Every
    # Mac reports deep colour, whatever the GPU.
    drawn = {"webGl:vendor": "Intel Inc.", "webGl:renderer": "Intel(R) HD Graphics 400, or similar",
             "navigator.hardwareConcurrency": 8, "screen.width": 1440, "screen.height": 900,
             "screen.colorDepth": 24, "screen.pixelDepth": 24}
    monkeypatch.setattr(utils, "from_fpgen", lambda *args, **kwargs: dict(drawn))
    launched, messages = launch(monkeypatch, {"navigator.userAgent": MAC["navigator.userAgent"]})
    assert launched["screen.colorDepth"] == 30
    assert launched["screen.pixelDepth"] == 30
    assert not incoherent(messages), messages
