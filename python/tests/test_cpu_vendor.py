"""cpu:vendor: the x86 CPU whose RCPPS/RSQRTPS estimates the canvas shows.

Skia's raster pipeline draws blend modes, perspective and inverted matrices
with RCPPS/RSQRTPS, whose low bits differ between Intel and AMD and agree
across generations of one vendor (browser/tests/cpu-estimates). The vendor is
part of the identity: drawn once with it, consistent with its GPU, and sent to
the browser as gfx.skia.cpu_vendor_estimates.
"""

import pytest

from camoufox import coherence
from camoufox.fingerprints import X86_INTEL_SHARE, set_cpu_vendor_default
from camoufox.pkgman import LAUNCHER_CONSTANTS

WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0"
NVIDIA = "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"


def _drawn(renderer, target_os="win", salt=0, cores=8):
    config = {"navigator.userAgent": WIN_UA, "navigator.hardwareConcurrency": cores}
    if renderer:
        config["webGl:renderer"] = renderer
    set_cpu_vendor_default(config, target_os, salt)
    return config.get("cpu:vendor")


def test_a_discrete_gpu_draws_firefoxs_x86_split():
    draws = [_drawn(NVIDIA, salt=salt) for salt in range(4000)]
    share = draws.count("intel") / len(draws)
    assert set(draws) == {"intel", "amd"}
    assert abs(share - X86_INTEL_SHARE) < 0.03


def test_the_draw_is_a_pure_function_of_the_identity():
    assert [_drawn(NVIDIA, salt=s) for s in range(50)] == [_drawn(NVIDIA, salt=s) for s in range(50)]


@pytest.mark.parametrize(
    "renderer,target_os,vendor",
    [
        ("ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar", "win", "intel"),
        ("ANGLE (Intel, Intel(R) HD Graphics 400 Direct3D11 vs_5_0 ps_5_0), or similar", "win", "intel"),
        ("Intel(R) HD Graphics, or similar", "lin", "intel"),
        ("ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar", "win", "amd"),
        ("Radeon HD 3200 Graphics, or similar", "lin", "amd"),
        # every x86 Mac has an Intel CPU, whatever its GPU
        ("Radeon R9 200 Series, or similar", "mac", "intel"),
        ("Intel(R) HD Graphics 400, or similar", "mac", "intel"),
    ],
)
def test_an_integrated_gpu_or_a_mac_decides_the_vendor(renderer, target_os, vendor):
    assert {_drawn(renderer, target_os, salt) for salt in range(200)} == {vendor}


def test_apple_silicon_has_no_x86_vendor():
    assert _drawn("Apple M1, or similar", "mac") is None


def test_a_callers_vendor_is_kept():
    config = {"cpu:vendor": "amd", "webGl:renderer": NVIDIA}
    set_cpu_vendor_default(config, "win")
    assert config["cpu:vendor"] == "amd"


def test_coherence_repairs_a_vendor_its_gpu_contradicts():
    config = {"cpu:vendor": "amd", "webGl:renderer": "Intel(R) HD Graphics, or similar"}
    assert [v.rule for v in coherence.validate(config, "lin")] == ["cpu-vendor-matches-gpu"]
    coherence.apply(config, "lin")
    assert config["cpu:vendor"] == "intel"
    config = {"cpu:vendor": "intel", "webGl:renderer": "Apple M1, or similar"}
    coherence.apply(config, "mac")
    assert "cpu:vendor" not in config


def test_coherence_keeps_a_callers_contradicting_vendor_and_reports_it():
    config = {"cpu:vendor": "amd", "webGl:renderer": "Intel(R) HD Graphics, or similar"}
    left = coherence.apply(config, "lin", keep=frozenset({"cpu:vendor"}))
    assert config["cpu:vendor"] == "amd"
    assert [(v.rule, v.kept) for v in left] == [("cpu-vendor-matches-gpu", ("cpu:vendor",))]


def test_the_pref_values_are_the_patchs():
    # SK_CPU_VENDOR_INTEL / SK_CPU_VENDOR_AMD in SkCpuEstimates.h
    assert LAUNCHER_CONSTANTS["cpuVendorEstimatesPref"] == {"intel": 1, "amd": 2}
