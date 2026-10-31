"""The browser renders at the identity's devicePixelRatio (#933)."""

import pytest

from camoufox import utils
from camoufox.fingerprints import Screen

from test_launch_environment import isolated_launch_dependencies  # noqa: F401

PREF = "layout.css.devPixelsPerPx"
WIN = {"navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0",
       "screen.width": 1382, "screen.height": 864, "window.outerWidth": 1280, "window.outerHeight": 900}


def prefs(dpr, **kwargs):
    return utils.launch_options(config={**WIN, "window.devicePixelRatio": dpr}, i_know_what_im_doing=True,
                                **{"headless": True, **kwargs})["firefox_user_prefs"]


def test_renders_at_the_claimed_scale(isolated_launch_dependencies):  # noqa: F811
    assert prefs(2.5)[PREF] == "2.5"
    assert prefs(1)[PREF] == "1"


def test_caller_pref_wins(isolated_launch_dependencies):  # noqa: F811
    assert prefs(2.5, firefox_user_prefs={PREF: "1.0"})[PREF] == "1.0"


def test_window_too_large_for_the_monitor_raises(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    monkeypatch.setattr(utils, "OS_NAME", "lin")
    with pytest.raises(ValueError, match="needs 3200 pixels, but this monitor has 1920"):
        prefs(2.5, headless=False, screen=Screen(max_width=1920, max_height=1080))
    assert prefs(1.25, headless=False, screen=Screen(max_width=1920, max_height=1200))[PREF] == "1.25"
