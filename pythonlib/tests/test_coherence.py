"""Every identity Camoufox can produce has to be a machine that could exist.

The pools are sampled independently -- navigator and screen from fpgen, the GPU
from fpgen's WebGL records, fonts and voices from their own catalogues -- so an
incoherent identity is assembled rather than inherited, and cleaning the pools
cannot prevent it. These tests run the assembled identity, from every source, past
camoufox.coherence.

Measured before the layer existed (2026-09-17): 7% of macOS identities paired
Apple Silicon with colorDepth 24; 2% of Windows identities reported
maxTouchPoints 256; and bundled presets carried screens no desktop has.

"Intel(R) HD Graphics 400" and "Radeon R9 200 Series" on macOS are not in that
list: they are the buckets Firefox reports for an Intel Mac's UHD 630 and a
Radeon Pro 5300M (its own TestCiMac and TestMacAmd cases). What an Intel Mac
cannot have is a notched Apple Silicon panel, or a core count no Intel Mac with
that GPU reports.
"""

import re
import sys
from os.path import dirname, join

import pytest

sys.path.insert(0, join(dirname(__file__), ".."))

from camoufox import coherence  # noqa: E402
from camoufox import fingerprints as fp  # noqa: E402
from camoufox.utils import get_target_os  # noqa: E402
from camoufox.webgl import sample_webgl_for_screen  # noqa: E402

from test_identity_salt import launch  # noqa: E402


def _firefox_bucket(raw):
    """The AMD and Intel branches of Firefox's SanitizeRenderer for a macOS
    GL_RENDERER (dom/canvas/SanitizeRenderer.cpp, FIREFOX_152_0_4_RELEASE)."""
    device = re.sub(r" OpenGL Engine$", "", raw)
    if any(part in device for part in ("REMBRANDT", "RENOIR", "Vega", "VII", "Fury")):
        return "Radeon R9 200 Series, or similar"
    radeon = re.search(r"Radeon.*?((R[579X]|HD) )?([0-9][0-9][0-9]+)", device)
    if radeon:
        if radeon.group(2) == "HD":
            model = int(radeon.group(3))
            return ("Radeon HD 5850" if model >= 5000 else "Radeon HD 3200 Graphics") + ", or similar"
        return "Radeon R9 200 Series, or similar"
    intel = re.search(r"Intel.*Graphics( P?([0-9][0-9][0-9]+))?", device)
    if intel:
        if not intel.group(1):
            return "Intel(R) HD Graphics, or similar"
        model = int(intel.group(2))
        return ("Intel(R) HD Graphics" if 1000 <= model < 5000 else "Intel(R) HD Graphics 400") + ", or similar"
    raise ValueError(f"not an AMD or Intel renderer: {raw!r}")


# What Intel Macs' GPUs report through Firefox. An Intel model number under
# 1000 or of 5000 and over lands in "HD Graphics 400"; a Radeon without an "HD"
# prefix lands in "R9 200 Series".
MAC_RENDERERS = [
    ("Intel(R) UHD Graphics 630", "Intel(R) HD Graphics 400, or similar"),  # Mac mini 2018, 15"/16" MacBook Pro
    ("Intel(R) Iris(TM) Plus Graphics 655", "Intel(R) HD Graphics 400, or similar"),  # 13" MacBook Pro 2018-19
    ("Intel HD Graphics 6000", "Intel(R) HD Graphics 400, or similar"),  # MacBook Air 2015-17
    ("Intel(R) Iris(TM) Plus Graphics", "Intel(R) HD Graphics, or similar"),  # MacBook Air 2020
    ("Intel HD Graphics 4000", "Intel(R) HD Graphics, or similar"),  # MacBook Air / Mac mini 2012
    ("AMD Radeon Pro 5300M OpenGL Engine", "Radeon R9 200 Series, or similar"),  # 16" MacBook Pro
    ("AMD Radeon Pro 560X OpenGL Engine", "Radeon R9 200 Series, or similar"),  # 15" MacBook Pro 2018
    ("AMD Radeon Pro Vega 56 OpenGL Engine", "Radeon R9 200 Series, or similar"),  # iMac Pro
]


class TestRules:
    """Each rule, against the value that motivated it."""

    def test_apple_silicon_never_has_fewer_than_eight_cores(self):
        config = {"webGl:renderer": "Apple M1, or similar", "navigator.hardwareConcurrency": 2}
        assert [v.rule for v in coherence.validate(config, "mac")] == ["apple-silicon-cores"]
        assert coherence.apply(config, "mac") == []
        assert config["navigator.hardwareConcurrency"] == 8

    def test_the_bucket_port_agrees_with_firefoxs_own_mac_cases(self):
        # dom/canvas/gtest/TestSanitizeRenderer.cpp, FIREFOX_152_0_4_RELEASE.
        assert _firefox_bucket("AMD Radeon Pro 5300M OpenGL Engine") == "Radeon R9 200 Series, or similar"
        assert _firefox_bucket("Intel(R) UHD Graphics 630") == "Intel(R) HD Graphics 400, or similar"

    @pytest.mark.parametrize("raw, bucket", MAC_RENDERERS)
    def test_an_intel_mac_reports_its_firefox_bucket(self, raw, bucket):
        assert _firefox_bucket(raw) == bucket
        assert coherence.gpu_fits_os(bucket, "mac"), raw

    def test_a_mac_cannot_report_an_angle_renderer(self):
        # Firefox 152 renders WebGL on macOS through CGL, and its sanitizer has
        # no ANGLE-on-Metal branch (Bug 2046027 added one after 152).
        config = {"webGl:renderer": "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0), or similar"}
        assert [v.rule for v in coherence.validate(config, "mac")] == ["gpu-matches-os"]

    def test_a_mac_cannot_report_a_software_rasteriser(self):
        assert not coherence.gpu_fits_os("llvmpipe, or similar", "mac")

    def test_an_intel_igp_mac_reports_its_physical_or_logical_cores(self):
        igp = "Intel(R) HD Graphics 400, or similar"
        for cores in (2, 4, 6, 8, 12, 16):
            assert coherence.validate({"webGl:renderer": igp, "navigator.hardwareConcurrency": cores}, "mac") == [], cores
        # No Mac that runs WebGL on its Intel IGP has more than 8 cores.
        for cores in (10, 14, 20, 24, 32):
            config = {"webGl:renderer": igp, "navigator.hardwareConcurrency": cores}
            assert [v.rule for v in coherence.validate(config, "mac")] == ["intel-mac-hardware"], cores

    def test_a_discrete_gpu_mac_reaches_the_mac_pro(self):
        amd = "Radeon R9 200 Series, or similar"
        for cores in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 48, 56):
            assert coherence.validate({"webGl:renderer": amd, "navigator.hardwareConcurrency": cores}, "mac") == [], cores
        config = {"webGl:renderer": amd, "navigator.hardwareConcurrency": 22}
        assert [v.rule for v in coherence.validate(config, "mac")] == ["intel-mac-hardware"]

    @pytest.mark.parametrize("renderer", [
        "Intel(R) HD Graphics 400, or similar",
        "Intel(R) HD Graphics, or similar",
        "Radeon R9 200 Series, or similar",
        "Radeon HD 3200 Graphics, or similar",
    ])
    def test_an_intel_mac_has_no_notched_panel(self, renderer):
        for width, height in ((1470, 956), (1512, 982), (1728, 1117), (2056, 1329), (1710, 1107)):
            config = {"webGl:renderer": renderer, "screen.width": width, "screen.height": height}
            assert [v.rule for v in coherence.validate(config, "mac")] == ["intel-mac-hardware"], (width, height)
        # The same panels are what Apple Silicon MacBooks report.
        assert coherence.validate({"webGl:renderer": "Apple M1, or similar", "screen.width": 1470,
                                   "screen.height": 956}, "mac") == []

    def test_a_preset_gpu_the_final_identity_contradicts_is_dropped(self):
        config = {"webGl:vendor": "Intel Inc.", "webGl:renderer": "Intel(R) HD Graphics 400, or similar",
                  "navigator.hardwareConcurrency": 20}
        assert [v.rule for v in coherence.drop_incoherent_source_values(config, "mac")] == ["intel-mac-hardware"]
        assert "webGl:renderer" not in config and "webGl:vendor" not in config

    def test_windows_renders_through_angle(self):
        assert coherence.gpu_fits_os("ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11), or similar", "win")
        assert not coherence.gpu_fits_os("Apple M1, or similar", "win")

    def test_apple_silicon_reports_deep_colour(self):
        # Measured on jobharvest-mac: colorDepth 30, (color: 10).
        config = {"webGl:renderer": "Apple M1, or similar", "screen.colorDepth": 24}
        assert [v.rule for v in coherence.validate(config, "mac")] == ["color-depth"]
        assert coherence.apply(config, "mac") == []
        assert config["screen.colorDepth"] == 30
        assert config["screen.pixelDepth"] == 30

    def test_colour_depth_is_24_or_30(self):
        config = {"screen.colorDepth": 32}
        assert [v.rule for v in coherence.validate(config, "lin")] == ["color-depth"]
        assert coherence.apply(config, "lin") == []
        assert config["screen.colorDepth"] == 24

    def test_touch_points_are_a_digitiser_count(self):
        config = {"navigator.maxTouchPoints": 256}
        assert [v.rule for v in coherence.validate(config, "win")] == ["touch-points"]
        assert coherence.apply(config, "win") == []
        assert config["navigator.maxTouchPoints"] == 0
        # 5 is real -- measured on win-i9, a touchscreen laptop -- and so are
        # 2 and 10; fpgen offers none of 2/5 and the presets carry 40.
        for real in (0, 1, 2, 5, 10):
            assert coherence.validate({"navigator.maxTouchPoints": real}, "win") == [], real

    def test_a_mac_has_no_touchscreen(self):
        config = {"navigator.maxTouchPoints": 5}
        assert [v.rule for v in coherence.validate(config, "mac")] == ["touch-points"]

    def test_device_pixel_ratio_is_a_real_display_mode(self):
        # 1.818 is a scraped artefact: a zoom level folded into the ratio.
        config = {"window.devicePixelRatio": 1.8181818181818181}
        assert [v.rule for v in coherence.validate(config, "win")] == ["device-pixel-ratio"]
        assert coherence.apply(config, "win") == []
        assert config["window.devicePixelRatio"] == 1.75
        # The three measured machines: 1 on linux, 2.5 on win-i9, 2 on the Mac.
        assert coherence.validate({"window.devicePixelRatio": 1}, "lin") == []
        assert coherence.validate({"window.devicePixelRatio": 2.5}, "win") == []
        assert coherence.validate({"window.devicePixelRatio": 2}, "mac") == []
        # macOS has no fractional scaling.
        assert [v.rule for v in coherence.validate({"window.devicePixelRatio": 1.5}, "mac")] == [
            "device-pixel-ratio"
        ]

    def test_desktop_screens_are_landscape(self):
        config = {"screen.width": 1440, "screen.height": 2560}
        assert [v.rule for v in coherence.validate(config, "win")] == ["screen-shape"]
        assert coherence.repair_screen_orientation(config)
        assert (config["screen.width"], config["screen.height"]) == (2560, 1440)

    def test_a_phone_viewport_is_not_a_desktop_screen(self):
        # One bundled preset reports this.
        assert [v.rule for v in coherence.validate({"screen.width": 736, "screen.height": 414}, "mac")] == [
            "screen-shape"
        ]

    def test_avail_never_exceeds_the_screen(self):
        config = {"screen.width": 1920, "screen.height": 1080, "screen.availWidth": 2000}
        assert [v.rule for v in coherence.validate(config, "lin")] == ["avail-bounds"]
        assert coherence.apply(config, "lin") == []
        assert config["screen.availWidth"] == 1920

    def test_platform_agrees_with_the_user_agent_arch(self):
        config = {
            "navigator.userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
            "navigator.platform": "Linux armv81",
        }
        assert [v.rule for v in coherence.validate(config, "lin")] == ["arch-agreement"]

    def test_the_real_machines_pass(self):
        """The three machines captured on 2026-09-17, as themselves."""
        real = [
            ("lin", {"navigator.userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
                     "navigator.platform": "Linux x86_64", "navigator.hardwareConcurrency": 16,
                     "navigator.maxTouchPoints": 0, "screen.width": 1920, "screen.height": 1080,
                     "screen.colorDepth": 24, "webGl:renderer": "Radeon HD 3200 Graphics, or similar"}),
            ("win", {"navigator.platform": "Win32", "navigator.hardwareConcurrency": 16,
                     "navigator.maxTouchPoints": 5, "screen.width": 1382, "screen.height": 864,
                     "screen.colorDepth": 24,
                     "webGl:renderer": "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar"}),
            ("mac", {"navigator.platform": "MacIntel", "navigator.hardwareConcurrency": 10,
                     "navigator.maxTouchPoints": 0, "screen.width": 2560, "screen.height": 1440,
                     "screen.colorDepth": 30, "webGl:renderer": "Apple M1, or similar"}),
            # fpgen model-2/2026's Radeon R9 200 macOS record: a 16" MacBook Pro
            # (6 physical cores) at its default scaled resolution.
            ("mac", {"navigator.platform": "MacIntel", "navigator.hardwareConcurrency": 6,
                     "navigator.maxTouchPoints": 0, "screen.width": 1792, "screen.height": 1120,
                     "screen.colorDepth": 30, "webGl:renderer": "Radeon R9 200 Series, or similar"}),
        ]
        for target_os, config in real:
            assert coherence.validate(config, target_os) == [], target_os


INTEL_MAC_BUCKETS = {"Intel(R) HD Graphics 400, or similar", "Radeon R9 200 Series, or similar"}


class TestIntelMacDraws:
    """The draw offers Intel Macs, but only beside a core count and a screen an
    Intel Mac could have."""

    def test_every_intel_mac_bucket_is_drawn(self):
        # fpgen model-2/2026 records each at 1.1% of Firefox on macOS.
        drawn = {sample_webgl_for_screen("mac", 2560, 1440, seed=s)["webGl:renderer"] for s in range(300)}
        assert INTEL_MAC_BUCKETS <= drawn

    def test_no_intel_mac_behind_a_notched_panel(self):
        for seed in range(300):
            renderer = sample_webgl_for_screen("mac", 1470, 956, seed=seed, cores=8)["webGl:renderer"]
            assert "Apple M" in renderer, (seed, renderer)

    def test_no_intel_igp_beside_a_core_count_no_intel_mac_reports(self):
        drawn = {sample_webgl_for_screen("mac", 2560, 1440, seed=s, cores=20)["webGl:renderer"] for s in range(300)}
        assert not any("Intel" in renderer for renderer in drawn), drawn

    def test_a_preset_gpu_is_checked_against_the_host_core_count(self, monkeypatch):
        """A launch replaces the preset's core count with the host's, after the
        preset's GPU has been read: the GPU has to fit the count that ships."""
        preset = dict(fp.load_presets("150")["presets"]["macos"][0])
        preset["navigator"] = {**preset["navigator"], "hardwareConcurrency": 8}
        preset["screen"] = {**preset["screen"], "width": 1440, "height": 900, "availWidth": 1440,
                            "availHeight": 875}
        preset["webgl"] = {**preset["webgl"], "unmaskedVendor": "Intel Inc.",
                           "unmaskedRenderer": "Intel(R) HD Graphics 400, or similar"}
        monkeypatch.setattr(fp, "host_cpu_count", lambda: 20)
        config = launch(os="macos", fingerprint_preset=preset)
        assert config["navigator.hardwareConcurrency"] == 20
        assert "Intel" not in config["webGl:renderer"]
        assert coherence.validate(config, "mac") == []


class TestEveryIdentityIsCoherent:
    """The assembled identity, from each source Camoufox draws one from."""

    @pytest.mark.parametrize("os_name", ["macos", "windows", "linux"])
    def test_generated_identities(self, os_name):
        for _ in range(40):
            config = launch(os=os_name)
            assert coherence.validate(config, get_target_os(config)) == []

    @pytest.mark.parametrize("os_name", ["macos", "windows", "linux"])
    def test_every_bundled_preset(self, os_name):
        for i, preset in enumerate(fp.load_presets("150")["presets"][os_name]):
            config = launch(os=os_name, fingerprint_preset=preset)
            assert coherence.validate(config, get_target_os(config)) == [], (os_name, i)


_MIDPOINT_REPAIRS = """
from camoufox import coherence
out = []
for os_key, steps in sorted(coherence.PLAUSIBLE_DPR.items()):
    steps = sorted(steps)
    for low, high in zip(steps, steps[1:]):
        config = {"window.devicePixelRatio": (low + high) / 2}
        coherence.apply(config, os_key)
        out.append(config["window.devicePixelRatio"])
print(out)
"""


def test_a_midpoint_repairs_to_the_lower_step_whether_or_not_bytecode_is_cached(tmp_path):
    """The steps were frozensets, and min() keeps the first of equal distances.
    A frozenset literal iterates in one order when compiled from source and in
    another when loaded back from a .pyc, so the same identity repaired
    differently on its first launch than on later ones."""
    import subprocess
    import sys
    from pathlib import Path

    env = {"PYTHONPYCACHEPREFIX": str(tmp_path), "PYTHONPATH": str(Path(coherence.__file__).parents[1])}
    runs = [
        subprocess.run([sys.executable, "-c", _MIDPOINT_REPAIRS], env=env, capture_output=True,
                       text=True, check=True).stdout
        for _ in range(2)  # the first compiles and writes the .pyc, the second loads it
    ]
    assert runs[0] == runs[1]
    lower = [low for _, steps in sorted(coherence.PLAUSIBLE_DPR.items())
             for low in sorted(steps)[:-1]]
    assert runs[0].strip() == str(lower)
