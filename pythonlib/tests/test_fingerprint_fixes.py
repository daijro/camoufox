"""
Tests for the BrowserForge fingerprint-correction helpers in
camoufox.fingerprints, ported to parity with the camoufox-js launcher.

Run with:
    cd pythonlib && python -m pytest tests/test_fingerprint_fixes.py -v

These guard the headless / impossible-geometry tells that BrowserForge
occasionally ships and that the camoufox-js wrapper already corrected but the
pythonlib did not.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import (  # noqa: E402
    clamp_screen_to_display,
    clamp_window_dimensions,
    clamp_window_position,
    fix_navigator_arch,
    fix_screen_no_taskbar,
    set_media_devices_defaults,
)


class TestFixNavigatorArch:
    def test_corrects_armv81_to_ua_arch(self):
        c = {
            "navigator.userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) ...",
            "navigator.platform": "Linux armv81",
            "navigator.oscpu": "Linux armv81",
        }
        fix_navigator_arch(c, "lin")
        assert c["navigator.platform"] == "Linux x86_64"
        assert c["navigator.oscpu"] == "Linux x86_64"

    def test_noop_when_already_consistent(self):
        c = {
            "navigator.userAgent": "... Linux x86_64 ...",
            "navigator.platform": "Linux x86_64",
            "navigator.oscpu": "Linux x86_64",
        }
        fix_navigator_arch(c, "lin")
        assert c["navigator.platform"] == "Linux x86_64"

    def test_only_runs_on_linux(self):
        c = {"navigator.userAgent": "... Macintosh ...", "navigator.platform": "MacIntel"}
        fix_navigator_arch(c, "mac")
        assert c["navigator.platform"] == "MacIntel"

    def test_noop_without_ua(self):
        c = {"navigator.platform": "Linux armv81"}
        fix_navigator_arch(c, "lin")
        assert c["navigator.platform"] == "Linux armv81"


class TestFixScreenNoTaskbar:
    def test_subtracts_taskbar_when_avail_equals_screen(self):
        c = {
            "screen.width": 1920,
            "screen.height": 1080,
            "screen.availWidth": 1920,
            "screen.availHeight": 1080,
            "window.outerHeight": 1080,
            "window.innerHeight": 1040,
        }
        fix_screen_no_taskbar(c, "lin")
        assert c["screen.availHeight"] == 1080 - 27  # linux panel
        assert c["window.outerHeight"] == 1053
        # chrome delta (1080-1040=40) preserved
        assert c["window.innerHeight"] == 1053 - 40

    def test_per_os_taskbar_height(self):
        for os_name, px in (("win", 40), ("mac", 25), ("lin", 27)):
            c = {
                "screen.width": 1920,
                "screen.height": 1080,
                "screen.availWidth": 1920,
                "screen.availHeight": 1080,
            }
            fix_screen_no_taskbar(c, os_name)
            assert c["screen.availHeight"] == 1080 - px

    def test_noop_when_avail_already_less_than_screen(self):
        c = {
            "screen.width": 1920,
            "screen.height": 1080,
            "screen.availWidth": 1920,
            "screen.availHeight": 1040,
        }
        fix_screen_no_taskbar(c, "lin")
        assert c["screen.availHeight"] == 1040


class TestClampWindowDimensions:
    def test_clamps_impossible_geometry_both_axes(self):
        c = {
            "screen.width": 1920,
            "screen.height": 1080,
            "screen.availWidth": 2000,  # > screen
            "window.outerWidth": 2200,  # > avail
            "window.innerWidth": 2100,  # > outer
        }
        clamp_window_dimensions(c)
        assert c["screen.availWidth"] == 1920
        assert c["window.outerWidth"] == 1920
        assert c["window.innerWidth"] <= c["window.outerWidth"]

    def test_preserves_chrome_delta(self):
        c = {
            "screen.width": 1000,
            "window.outerWidth": 1200,  # 200 over screen
            "window.innerWidth": 1180,  # 20px chrome
        }
        clamp_window_dimensions(c)
        assert c["window.outerWidth"] == 1000
        assert c["window.innerWidth"] == 1000 - 20

    def test_noop_when_hierarchy_already_valid(self):
        c = {
            "screen.width": 1920,
            "screen.availWidth": 1920,
            "window.outerWidth": 1280,
            "window.innerWidth": 1264,
        }
        clamp_window_dimensions(c)
        assert c["window.outerWidth"] == 1280
        assert c["window.innerWidth"] == 1264


class TestClampScreenToDisplay:
    def test_shrinks_screen_to_display(self):
        # BrowserForge routinely ships a 2560x1440 fingerprint to a 1366x768
        # laptop; browser-init then resizes the real window past the monitor.
        c = {
            "screen.width": 2560,
            "screen.height": 1440,
            "screen.availWidth": 2560,
            "screen.availHeight": 1400,
        }
        clamp_screen_to_display(c, 1366, 768)
        assert c["screen.width"] == 1366
        assert c["screen.height"] == 768
        # taskbar delta (1440-1400=40) preserved, so fix_screen_no_taskbar's
        # avail < height invariant still holds
        assert c["screen.availWidth"] == 1366
        assert c["screen.availHeight"] == 768 - 40

    def test_noop_when_already_within_display(self):
        c = {"screen.width": 1280, "screen.height": 720, "screen.availHeight": 700}
        clamp_screen_to_display(c, 1366, 768)
        assert c["screen.width"] == 1280
        assert c["screen.height"] == 720
        assert c["screen.availHeight"] == 700

    def test_ignores_unset_bounds(self):
        c = {"screen.width": 2560, "screen.height": 1440}
        clamp_screen_to_display(c, None, None)
        assert c["screen.width"] == 2560
        assert c["screen.height"] == 1440

    def test_avail_never_drops_below_one(self):
        # taskbar delta larger than the display must not produce a <= 0 avail
        c = {"screen.height": 2000, "screen.availHeight": 100}
        clamp_screen_to_display(c, None, 768)
        assert c["screen.availHeight"] >= 1

    def test_clamped_result_survives_cascade(self):
        c = {
            "screen.width": 2560,
            "screen.height": 1440,
            "screen.availWidth": 2560,
            "screen.availHeight": 1400,
            "window.outerWidth": 1920,
            "window.outerHeight": 1055,
            "window.innerWidth": 1920,
            "window.innerHeight": 1000,
        }
        clamp_screen_to_display(c, 1366, 768)
        clamp_window_dimensions(c)
        assert c["window.outerWidth"] <= c["screen.availWidth"] <= c["screen.width"] == 1366
        assert c["window.outerHeight"] <= c["screen.availHeight"] <= c["screen.height"] == 768
        assert c["window.innerWidth"] <= c["window.outerWidth"]
        assert c["window.innerHeight"] <= c["window.outerHeight"]


class TestClampWindowPosition:
    def test_pulls_window_back_inside_screen(self):
        c = {
            "screen.width": 1366,
            "screen.height": 768,
            "window.outerWidth": 1366,
            "window.outerHeight": 728,
            "window.screenX": 250,
            "window.screenY": 281,
        }
        clamp_window_position(c)
        assert c["window.screenX"] == 0
        assert c["window.screenY"] == 40

    def test_noop_when_window_already_inside(self):
        c = {
            "screen.width": 1920,
            "screen.height": 1080,
            "window.outerWidth": 1280,
            "window.outerHeight": 720,
            "window.screenX": 100,
            "window.screenY": 50,
        }
        clamp_window_position(c)
        assert c["window.screenX"] == 100
        assert c["window.screenY"] == 50

    def test_never_negative(self):
        c = {
            "screen.width": 800,
            "window.outerWidth": 1000,  # wider than screen
            "window.screenX": 50,
        }
        clamp_window_position(c)
        assert c["window.screenX"] == 0


class TestSetMediaDevicesDefaults:
    def test_sets_one_mic_one_cam(self):
        c = {}
        set_media_devices_defaults(c)
        assert c["mediaDevices:enabled"] is True
        assert c["mediaDevices:micros"] == 1
        assert c["mediaDevices:webcams"] == 1
        assert c["mediaDevices:speakers"] == 0

    def test_respects_user_set_media_devices(self):
        c = {"mediaDevices:webcams": 5}
        set_media_devices_defaults(c)
        assert c == {"mediaDevices:webcams": 5}
