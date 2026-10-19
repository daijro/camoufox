"""
Tests for the fingerprint-correction helpers in camoufox.fingerprints.

Run with:
    cd python && python -m pytest tests/test_fingerprint_fixes.py -v

These guard the headless / impossible-geometry tells a generated fingerprint
can carry. typescript/tests/fingerprints.test.ts mirrors them.
"""


from camoufox.fingerprints import (
    clamp_screen_to_display,
    clamp_window_dimensions,
    clamp_window_position,
    fix_navigator_arch,
    follow_baseline_protection,
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


class TestFollowBaselineProtection:
    """The browser reports these through Firefox's baseline fingerprinting
    protection whatever the config says, so the config must claim the same.
    A Linux identity claiming availHeight 1053 on a 1080 screen read 1080."""

    def test_avail_is_the_screen_less_the_baseline_taskbar(self):
        for os_name, px in (("win", 48), ("mac", 76), ("lin", 0)):
            c = {
                "screen.width": 1920,
                "screen.height": 1080,
                "screen.availWidth": 1900,
                "screen.availHeight": 1053,
            }
            follow_baseline_protection(c, os_name)
            assert c["screen.availWidth"] == 1920
            assert c["screen.availHeight"] == 1080 - px

    def test_multi_touch_collapses_to_five(self):
        for touch, seen in ((0, 0), (1, 1), (2, 5), (10, 5)):
            c = {"navigator.maxTouchPoints": touch}
            follow_baseline_protection(c, "win")
            assert c["navigator.maxTouchPoints"] == seen

    def test_window_fits_the_available_screen(self):
        c = {
            "screen.width": 1920,
            "screen.height": 1080,
            "screen.availHeight": 1040,
            "window.outerHeight": 1040,
            "window.innerHeight": 1000,
        }
        follow_baseline_protection(c, "win")
        clamp_window_dimensions(c)
        assert c["window.outerHeight"] == 1032
        assert c["window.innerHeight"] == 1032 - 40


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
        # A 2560x1440 fingerprint on a 1366x768 laptop: browser-init would
        # resize the real window past the monitor.
        c = {
            "screen.width": 2560,
            "screen.height": 1440,
            "screen.availWidth": 2560,
            "screen.availHeight": 1400,
        }
        clamp_screen_to_display(c, 1366, 768)
        assert c["screen.width"] == 1366
        assert c["screen.height"] == 768
        # taskbar delta (1440-1400=40) preserved
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
    def test_draws_common_desktop_devices(self):
        # A pre-permission page only sees "has a mic" / "has a camera"; the draw
        # is seeded by the identity and follows the common desktop population.
        c = {"navigator.userAgent": "ua", "navigator.platform": "Win32"}
        set_media_devices_defaults(c)
        assert c["mediaDevices:enabled"] is True
        # counts and the post-grant label/group lists agree
        for kind, key in (("micros", "microphone"), ("webcams", "webcam"), ("speakers", "speaker")):
            n = c[f"mediaDevices:{kind}"]
            assert n >= 0
            assert len(c[f"mediaDevices:{key}Labels"]) == n
            assert len(c[f"mediaDevices:{key}Groups"]) == n
        # a Windows machine always has an output, in WASAPI label form
        assert c["mediaDevices:speakers"] >= 1
        assert all("(" in s for s in c["mediaDevices:speakerLabels"])
        again = {"navigator.userAgent": "ua", "navigator.platform": "Win32"}
        set_media_devices_defaults(again)
        assert again == c
        # over many identities laptops dominate Windows: most have both
        mics = cams = 0
        for i in range(400):
            d = {"navigator.userAgent": f"ua{i}", "navigator.platform": "Win32"}
            set_media_devices_defaults(d)
            mics += d["mediaDevices:micros"] > 0
            cams += d["mediaDevices:webcams"] > 0
        assert 0.8 < mics / 400 < 1.0
        assert 0.55 < cams / 400 < 0.95

    def test_per_os_label_style(self):
        from camoufox.fingerprints import draw_media_devices

        mac = draw_media_devices("mac", 7)
        assert all(not s.startswith("Microphone (") for s in mac["mediaDevices:microphoneLabels"])
        lin = draw_media_devices("lin", 7)
        # PulseAudio lists a monitor source per output as a capture device
        outs = lin["mediaDevices:speakerLabels"]
        assert all(f"Monitor of {o}" in lin["mediaDevices:microphoneLabels"] for o in outs)
        # a sound card's mic and speakers share a group, like a real groupId
        win = draw_media_devices("win", 11)
        if win["mediaDevices:micros"] and win["mediaDevices:speakers"]:
            assert win["mediaDevices:microphoneGroups"][0] == win["mediaDevices:speakerGroups"][0]
        # never the fake engine's names
        for os_key in ("win", "mac", "lin"):
            for seed in range(50):
                d = draw_media_devices(os_key, seed)
                mics = d["mediaDevices:microphoneLabels"]
                cams = d["mediaDevices:webcamLabels"]
                assert "Default Audio Device" not in mics
                assert "Default Video Device" not in cams
                # distinct within a kind (macOS names a webcam and its mic alike)
                assert len(set(mics)) == len(mics)
                assert len(set(cams)) == len(cams)

    def test_respects_user_set_media_devices(self):
        c = {"mediaDevices:webcams": 5}
        set_media_devices_defaults(c)
        assert c == {"mediaDevices:webcams": 5}


class TestFixHardwareConcurrency:
    def test_keeps_a_plausible_draw_the_host_can_be_pinned_to(self, monkeypatch):
        # The fingerprint's value survives when it is a count a real desktop
        # ships with AND the browser can be pinned to it (reported == measurable
        # by construction).
        from camoufox import cpu_affinity, fingerprints as fp

        monkeypatch.setattr(cpu_affinity, "supported", lambda: True)
        monkeypatch.setattr(fp, "host_cpu_count", lambda: 16)
        for drawn in (4, 6, 8, 10, 12, 14, 16):
            c = {"navigator.hardwareConcurrency": drawn}
            fp.fix_hardware_concurrency(c)
            assert c["navigator.hardwareConcurrency"] == drawn

    def test_snaps_implausible_draws_down_into_the_table(self, monkeypatch):
        # Counts no desktop ships with (2, odd counts) snap DOWN into
        # PLAUSIBLE_CORE_COUNTS, with the table floor for anything below it.
        from camoufox import cpu_affinity, fingerprints as fp

        monkeypatch.setattr(cpu_affinity, "supported", lambda: True)
        monkeypatch.setattr(fp, "host_cpu_count", lambda: 16)
        for drawn, expected in ((1, 4), (2, 4), (3, 4), (5, 4), (7, 6), (9, 8),
                                (11, 10), (13, 12), (15, 14), (32, 16)):
            c = {"navigator.hardwareConcurrency": drawn}
            fp.fix_hardware_concurrency(c)
            assert c["navigator.hardwareConcurrency"] == expected, drawn
        # never above what the host can be pinned to
        monkeypatch.setattr(fp, "host_cpu_count", lambda: 4)
        c = {"navigator.hardwareConcurrency": 2}
        fp.fix_hardware_concurrency(c)
        assert c["navigator.hardwareConcurrency"] == 4

    def test_snaps_host_parallelism_when_it_cannot_pin(self, monkeypatch):
        # The host count, snapped DOWN into the
        # counts real machines ship with; the tails report 32 / 4. Used when the
        # draw exceeds the host or the host cannot pin (macOS).
        # 18/22/24/28/32 are in the table (recorded on real devices); 2 is NOT,
        # although it is recorded, because 2 is the resistFingerprinting value.
        from camoufox import cpu_affinity, fingerprints as fp

        monkeypatch.setattr(cpu_affinity, "supported", lambda: False)
        for host, expected in (
            (16, 16),
            (10, 10),
            (24, 24),
            (26, 24),
            (32, 32),
            (64, 32),
            (22, 22),
            (7, 6),
            (5, 4),
            (2, 4),
            (9, 8),
        ):
            monkeypatch.setattr(fp, "host_cpu_count", lambda host=host: host)
            c = {"navigator.hardwareConcurrency": 2}
            fp.fix_hardware_concurrency(c)
            assert c["navigator.hardwareConcurrency"] == expected, host
        # a draw above the host count cannot be honoured even where pinning works
        monkeypatch.setattr(cpu_affinity, "supported", lambda: True)
        monkeypatch.setattr(fp, "host_cpu_count", lambda: 8)
        c = {"navigator.hardwareConcurrency": 32}
        fp.fix_hardware_concurrency(c)
        assert c["navigator.hardwareConcurrency"] == 8

    def test_no_host_count_leaves_the_draw(self, monkeypatch):
        from camoufox import fingerprints as fp

        monkeypatch.setattr(fp, "host_cpu_count", lambda: None)
        c = {"navigator.hardwareConcurrency": 8}
        fp.fix_hardware_concurrency(c)
        assert c["navigator.hardwareConcurrency"] == 8
