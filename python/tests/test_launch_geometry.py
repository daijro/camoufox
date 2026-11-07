"""
Launch-level guards for the display clamp in launch_options().

Run with:
    cd python && python -m pytest tests/test_launch_geometry.py -v
"""

import os
from contextlib import contextmanager
from unittest import mock

import orjson
import pytest
from camoufox.fingerprints import Screen

from camoufox import utils

# What get_screen_cons() reports under the Xvfb that headless='virtual' starts:
# virtdisplay.py sizes it "1x1x24", and launch_options mutates os.environ's
# DISPLAY, so the parent process enumerates that stub as its only monitor.
XVFB_STUB = Screen(max_width=1, max_height=1)


@contextmanager
def host(screen_cons):
    """Run launch_options() against a stubbed host, without touching the disk.

    has_display() is stubbed alongside get_screen_cons() because launch_options
    guards the one with the other:

        screen_cons = screen or (get_screen_cons(headless) if has_display(env) else None)

    Stubbing only get_screen_cons left the result depending on the *ambient*
    display: with DISPLAY set the stub was consulted and the clamp ran, and
    without it screen_cons came back None and the clamp was skipped, so all
    fifteen TestHeadfulFitsOnDisplay draws failed. That passed on every
    developer machine and failed the first time the suite ran on a headless CI
    runner.
    """
    with mock.patch.object(utils, "get_screen_cons", lambda headless: screen_cons), (
        mock.patch.object(utils, "has_display", lambda env: True)
    ), mock.patch.object(utils, "installed_verstr", lambda: "150.0.2"), (
        mock.patch.object(utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox")
    ):
        yield


def config_of(options):
    """Reassemble the chunked CAMOU_CONFIG_<n> env vars into a dict."""
    env = options["env"]
    chunks = sorted(
        (int(k.rsplit("_", 1)[1]), v) for k, v in env.items() if k.startswith("CAMOU_CONFIG_")
    )
    return orjson.loads("".join(chunk for _, chunk in chunks))


def launch(**kwargs):
    kwargs.setdefault("os", "windows")
    kwargs.setdefault("i_know_what_im_doing", True)
    return config_of(utils.launch_options(**kwargs))


class TestVirtualDisplayIsNotAScreen:
    """headless='virtual' arrives here as headless=False (async_api rewrites it),
    so the headful gate alone would clamp the fingerprint to the 1x1 Xvfb."""

    def test_fingerprint_is_not_shrunk_to_the_xvfb(self):
        with host(XVFB_STUB):
            config = launch(headless=False, virtual_display=":99")

        assert config["screen.width"] > 1
        assert config["screen.height"] > 1
        assert config["window.outerWidth"] > 1

    def test_screen_dimensions_stay_valid(self):
        """Clamping to 1x1 drives availHeight negative once the taskbar is
        subtracted, which validate_config rejects as a uint."""
        with host(XVFB_STUB):
            config = launch(headless=False, virtual_display=":99")

        for key, value in config.items():
            if key.startswith("screen.") or key.startswith("window.outer"):
                assert value >= 0, f"{key} is negative: {value}"


# A 1920x1080 panel at 150% Windows scaling, in CSS pixels
SCALED_DISPLAY = Screen(max_width=1280, max_height=720)

# Config key -> the display bound it must respect
BOUNDED_BY = {
    "screen.width": "max_width",
    "screen.height": "max_height",
    "window.outerWidth": "max_width",
    "window.outerHeight": "max_height",
}


class TestHeadfulFitsOnDisplay:
    """The generator drops a screen constraint it cannot satisfy, so assert the
    outcome rather than trusting the constraint to have been honoured."""

    @pytest.mark.parametrize("attempt", range(15))
    def test_generated_geometry_never_exceeds_the_display(self, attempt):
        with host(SCALED_DISPLAY):
            config = launch(headless=False)

        for key, bound in BOUNDED_BY.items():
            limit = getattr(SCALED_DISPLAY, bound)
            assert config[key] <= limit, f"{key}={config[key]} exceeds {limit}"

    def test_geometry_stays_internally_consistent(self):
        with host(SCALED_DISPLAY):
            config = launch(headless=False)

        assert config["screen.availWidth"] <= config["screen.width"]
        assert config["screen.availHeight"] < config["screen.height"]  # taskbar
        assert config["window.outerWidth"] <= config["screen.availWidth"]
        assert config["window.outerHeight"] <= config["screen.availHeight"]

    def test_unprobeable_display_is_not_clamped(self):
        """A host we cannot measure must not silently shrink the fingerprint."""
        with host(None), mock.patch.object(utils, "clamp_screen_to_display") as clamp:
            launch(headless=False)

        clamp.assert_not_called()

class TestViewportOperationsDoNotDeadlock:
    """The window's inner dimensions must stay real.

    Playwright's setViewportSize resizes the window and then waits for the page
    to report the size it asked for. A spoofed innerWidth/innerHeight never
    changes, so that wait never ends -- the same trap no_viewport exists for
    (#666), reached through an explicit call instead.

    Mapping fpgen's real inner dimensions hung
    browser/tests/playwright/patches/humanize-edge-deadlock.py for the full 600s
    CI timeout.
    """

    def test_inner_dimensions_are_never_spoofed(self):
        for os_name in ("linux", "windows", "macos"):
            for _ in range(5):
                config = launch(os=os_name)
                assert "window.innerWidth" not in config, os_name
                assert "window.innerHeight" not in config, os_name


def _zoomed_windows_fingerprint(dpr):
    """fpgen's 1920x1080 monitor recorded at a 110% browser zoom: every CSS size
    shrunk by the zoom folded into the ratio."""
    from camoufox.fingerprints import generate_fingerprint

    fp = generate_fingerprint(os="windows")
    fp["screen"].update(width=1760, height=990, availWidth=1760, availHeight=946, availLeft=0, availTop=0)
    fp["window"].update(devicePixelRatio=dpr, outerWidth=1760, outerHeight=953, screenX=-7, screenY=-7)
    return fp


def test_a_zoomed_fpgen_ratio_claims_the_display_it_was_recorded_on():
    # fpgen.yml leaves the ratio unmapped, so the page saw 1 while the screen
    # kept the zoomed 1760x990: a 1760x990 monitor that, rendered at 1 on the
    # real 1920x1080 one, made a fullscreen window 1920x1080 against
    # screen.width 1760 (cg.13 on WSLg). A ratio no display offers is a zoom,
    # so it is repaired to the display's scale with the geometry rescaled.
    with host(Screen(max_width=1920, max_height=1080)):
        config = config_of(utils.launch_options(
            headless=True, os="windows", fingerprint=_zoomed_windows_fingerprint(1.0909090909090908),
            i_know_what_im_doing=True))
    assert config["window.devicePixelRatio"] == 1
    assert (config["screen.width"], config["screen.height"]) == (1920, 1080)
    assert config["screen.availHeight"] == 1032


def test_a_real_display_scale_from_fpgen_stays_unmapped():
    # 1.25 is a scale Windows offers: the identity is left as fpgen.yml maps it.
    with host(Screen(max_width=1920, max_height=1080)):
        config = config_of(utils.launch_options(
            headless=True, os="windows", fingerprint=_zoomed_windows_fingerprint(1.25),
            i_know_what_im_doing=True))
    assert "window.devicePixelRatio" not in config
    assert config["screen.width"] == 1760


def test_a_zoomed_fpgen_ratio_follows_the_caller_s_render_scale():
    # A caller who sets layout.css.devPixelsPerPx decides the scale the page
    # renders at. The zoom repair moved 1.818 (175% with a zoom folded in) to
    # 1.75 regardless, so the page reported devicePixelRatio 1.75 while
    # matchMedia('(resolution: 1dppx)') matched: a pairing no Firefox has
    # (font-fallback-windows.py, pinned to 1, failed on such a draw). The
    # repair now targets the caller's scale, rescaling the geometry to it.
    drawn = 1.8181818181818181
    with host(Screen(max_width=3840, max_height=2160)):
        opts = utils.launch_options(
            headless=True, os="windows", fingerprint=_zoomed_windows_fingerprint(drawn),
            firefox_user_prefs={"layout.css.devPixelsPerPx": "1"}, i_know_what_im_doing=True)
    config = config_of(opts)
    assert config["window.devicePixelRatio"] == 1
    assert opts["firefox_user_prefs"]["layout.css.devPixelsPerPx"] == "1"
    assert config["screen.width"] == round(1760 * drawn)
