"""
Launch-level guards for the display clamp in launch_options().

Run with:
    cd pythonlib && python -m pytest tests/test_launch_geometry.py -v
"""

import os
import sys
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import orjson  # noqa: E402
import pytest  # noqa: E402
from browserforge.fingerprints import Screen  # noqa: E402

from camoufox import utils  # noqa: E402

# What get_screen_cons() reports under the Xvfb that headless='virtual' starts:
# virtdisplay.py sizes it "1x1x24", and launch_options mutates os.environ's
# DISPLAY, so the parent process enumerates that stub as its only monitor.
XVFB_STUB = Screen(max_width=1, max_height=1)


@contextmanager
def host(screen_cons):
    """Run launch_options() against a stubbed host, without touching the disk."""
    with mock.patch.object(utils, "get_screen_cons", lambda headless: screen_cons), (
        mock.patch.object(utils, "installed_verstr", lambda: "150.0.2")
    ), mock.patch.object(utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox"):
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
        """Clamping to 1x1 drives availHeight negative once fix_screen_no_taskbar
        subtracts the taskbar, which validate_config rejects as a uint."""
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
    """BrowserForge drops a screen constraint it cannot satisfy, so assert the
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
