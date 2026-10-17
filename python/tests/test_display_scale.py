"""display_scale=True renders at the identity's drawn display scale.

fpgen draws screens at a scale (1536x864 is a 1920x1080 panel at 125%), and
rendering those at 1 left devicePixelRatio and (resolution) contradicting the
screen. layout.css.devPixelsPerPx makes the scale real, so every value agrees.
"""

import pytest

from camoufox import utils
from camoufox.fingerprints import Screen

from test_launch_environment import isolated_launch_dependencies  # noqa: F401

WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:156.0) Gecko/20100101 Firefox/156.0"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:156.0) Gecko/20100101 Firefox/156.0"
PREF = "layout.css.devPixelsPerPx"


def draw(width, height, dpr):
    return {"screen": {"width": width, "height": height}, "window": {"devicePixelRatio": dpr}}


def prefs(ua, fingerprint, **kwargs):
    kwargs.setdefault("display_scale", True)
    return utils.launch_options(
        config={"navigator.userAgent": ua},
        fingerprint=fingerprint,
        i_know_what_im_doing=True,
        **kwargs,
    )["firefox_user_prefs"]


def test_off_by_default(isolated_launch_dependencies):  # noqa: F811
    assert PREF not in prefs(WIN_UA, draw(1536, 864, 1.25), headless=True, display_scale=None)


def test_drawn_scale_is_rendered(isolated_launch_dependencies):  # noqa: F811
    assert prefs(WIN_UA, draw(1536, 864, 1.25), headless=True)[PREF] == "1.25"


def test_unit_scale_sets_nothing(isolated_launch_dependencies):  # noqa: F811
    assert PREF not in prefs(WIN_UA, draw(1920, 1080, 1), headless=True)


def test_scraped_ratio_snaps_to_a_real_scaling_step(isolated_launch_dependencies):  # noqa: F811
    # 1.818 is a browser zoom folded into the ratio; Windows offers 175%.
    assert prefs(WIN_UA, draw(1056, 594, 1.8181818181818181), headless=True)[PREF] == "1.75"
    # macOS has 1x and 2x only.
    assert prefs(MAC_UA, draw(1512, 982, 1.8181818181818181), headless=True)[PREF] == "2"


def test_headful_scale_that_fits_the_monitor(isolated_launch_dependencies):  # noqa: F811
    # 1536x864 at 125% is exactly a 1920x1080 panel.
    p = prefs(WIN_UA, draw(1536, 864, 1.25), headless=False,
              screen=Screen(max_width=1920, max_height=1080))
    assert p[PREF] == "1.25"


def test_headful_scale_that_does_not_fit_stays_at_1(isolated_launch_dependencies):  # noqa: F811
    # A 1512x982 Mac at 2x needs 3024x1964 physical pixels.
    p = prefs(MAC_UA, draw(1512, 982, 2), headless=False,
              screen=Screen(max_width=1920, max_height=1080))
    assert PREF not in p


def test_caller_pref_wins(isolated_launch_dependencies):  # noqa: F811
    p = prefs(WIN_UA, draw(1536, 864, 1.25), headless=True, firefox_user_prefs={PREF: "1.0"})
    assert p[PREF] == "1.0"


def test_fresh_draws_are_redrawn_until_they_fit(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    draws = iter([draw(1512, 982, 2), draw(1512, 982, 2), draw(1440, 900, 1)])
    monkeypatch.setattr(utils, "generate_fingerprint", lambda **kw: next(draws))
    p = utils.launch_options(
        config={"navigator.userAgent": MAC_UA},
        headless=False,
        screen=Screen(max_width=1920, max_height=1080),
        display_scale=True,
        i_know_what_im_doing=True,
    )["firefox_user_prefs"]
    assert PREF not in p
    with pytest.raises(StopIteration):
        next(draws)


def test_fresh_draws_are_not_redrawn_when_off(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    draws = iter([draw(1512, 982, 2), draw(1440, 900, 1)])
    monkeypatch.setattr(utils, "generate_fingerprint", lambda **kw: next(draws))
    utils.launch_options(
        config={"navigator.userAgent": MAC_UA},
        headless=False,
        screen=Screen(max_width=1920, max_height=1080),
        i_know_what_im_doing=True,
    )
    assert next(draws) == draw(1440, 900, 1)
