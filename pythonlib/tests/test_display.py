"""
Tests for camoufox.display -- probing the host monitor in CSS pixels.

Guards daijro/camoufox#425: with Windows display scaling enabled, screeninfo
reports physical pixels while Firefox lays windows out in CSS pixels, so the
browser window opened larger than the screen.

Run with:
    cd pythonlib && python -m pytest tests/test_display.py -v
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from camoufox import display  # noqa: E402


def monitor(width, height, x=0, y=0):
    return SimpleNamespace(width=width, height=height, x=x, y=y)


@pytest.fixture
def monitors(monkeypatch):
    """Stub out screeninfo with an explicit monitor list."""

    def _set(*found):
        monkeypatch.setattr(display, "get_monitors", lambda: list(found))

    return _set


class TestLargestDisplay:
    def test_reports_unscaled_display_verbatim(self, monkeypatch, monitors):
        monkeypatch.setattr(display, "OS_NAME", "lin")
        monitors(monitor(1920, 1080))
        assert display.largest_display() == (1920, 1080)

    @pytest.mark.parametrize(
        ("dpi", "expected"),
        [(96, (1920, 1080)), (120, (1536, 864)), (144, (1280, 720)), (192, (960, 540))],
    )
    def test_windows_scaling_converts_to_css_pixels(
        self, monkeypatch, monitors, dpi, expected
    ):
        monkeypatch.setattr(display, "OS_NAME", "win")
        monkeypatch.setattr(display, "_windows_monitor_dpi", lambda m: dpi)
        monitors(monitor(1920, 1080))
        assert display.largest_display() == expected

    def test_scaling_is_windows_only(self, monkeypatch, monitors):
        """macOS and X11 already report CSS pixels; never rescale them."""
        monkeypatch.setattr(display, "_windows_monitor_dpi", lambda m: 192)
        monitors(monitor(1920, 1080))
        for os_name in ("mac", "lin"):
            monkeypatch.setattr(display, "OS_NAME", os_name)
            assert display.largest_display() == (1920, 1080)

    def test_falls_back_to_1x_when_dpi_lookup_fails(self, monkeypatch, monitors):
        def unavailable(_):
            raise OSError("GetDpiForMonitor failed")

        monkeypatch.setattr(display, "OS_NAME", "win")
        monkeypatch.setattr(display, "_windows_monitor_dpi", unavailable)
        monitors(monitor(1920, 1080))
        assert display.largest_display() == (1920, 1080)

    def test_falls_back_to_1x_on_nonsense_dpi(self, monkeypatch, monitors):
        monkeypatch.setattr(display, "OS_NAME", "win")
        monkeypatch.setattr(display, "_windows_monitor_dpi", lambda m: 0)
        monitors(monitor(1920, 1080))
        assert display.largest_display() == (1920, 1080)

    def test_picks_the_roomiest_monitor(self, monkeypatch, monitors):
        monkeypatch.setattr(display, "OS_NAME", "lin")
        monitors(monitor(1280, 720), monitor(2560, 1440), monitor(1920, 1080))
        assert display.largest_display() == (2560, 1440)

    def test_none_when_no_monitors(self, monitors):
        monitors()
        assert display.largest_display() is None

    def test_none_when_enumeration_raises(self, monkeypatch):
        def boom():
            raise RuntimeError("no display")

        monkeypatch.setattr(display, "get_monitors", boom)
        assert display.largest_display() is None


class TestHasDisplay:
    @pytest.mark.parametrize("os_name", ["win", "mac"])
    def test_always_present_off_linux(self, monkeypatch, os_name):
        """Regression: keying off DISPLAY alone skipped Windows/macOS entirely."""
        monkeypatch.setattr(display, "OS_NAME", os_name)
        assert display.has_display({}) is True

    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({}, False),
            ({"DISPLAY": ":0"}, True),
            ({"WAYLAND_DISPLAY": "wayland-0"}, True),
            ({"DISPLAY": ""}, False),
        ],
    )
    def test_linux_requires_a_session(self, monkeypatch, env, expected):
        monkeypatch.setattr(display, "OS_NAME", "lin")
        assert display.has_display(env) is expected
