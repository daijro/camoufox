"""cpu:arch and cpu:manufacturer: the CPU whose arithmetic the page sees.

Firefox never reports the CPU, but canvas pixels, Web Audio samples, encoded
Opus, relaxed-SIMD wasm and NaN signs differ between x86-64 and ARM64, and
canvas and Opus between Intel's and AMD's RCPPS/RSQRTPS (browser/tests/
cpu-probe). The CPU is part of the identity: drawn once with it, consistent
with its GPU and OS, and sent to the browser as general.cpu_identity.
"""

import pytest

from camoufox import coherence
from camoufox.fingerprints import X86_INTEL_SHARE, set_cpu_default
from camoufox.pkgman import LAUNCHER_CONSTANTS
from camoufox.utils import _os_for_cpu, cpu_identity_pref, vpx_realtime_only

WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0"
NVIDIA = "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"
APPLE = "Apple M1, or similar"


def _drawn(renderer, target_os="win", salt=0, cores=8):
    config = {"navigator.userAgent": WIN_UA, "navigator.hardwareConcurrency": cores}
    if renderer:
        config["webGl:renderer"] = renderer
    set_cpu_default(config, target_os, salt)
    return config.get("cpu:arch"), config.get("cpu:manufacturer")


# --- the caller's option -----------------------------------------------------

@pytest.mark.parametrize(
    "cpu,target_os,resolved",
    [
        ({"arch": "x86", "manufacturer": "intel"}, "mac", ("x86", "intel")),
        ({"arch": "arm", "manufacturer": "apple"}, "mac", ("arm", "apple")),
        ({"manufacturer": "apple"}, "mac", ("arm", "apple")),
        ({"manufacturer": "amd"}, "win", ("x86", "amd")),
        ({"arch": "arm", "manufacturer": "qualcomm"}, "win", ("arm", "qualcomm")),
        ({"manufacturer": "broadcom"}, "lin", ("arm", "broadcom")),
        ({"manufacturer": "apple"}, "lin", ("arm", "apple")),
        ({"arch": "x86"}, "lin", ("x86", None)),
    ],
)
def test_real_machines_resolve(cpu, target_os, resolved):
    got = coherence.resolve_cpu(cpu, target_os)
    assert (got.get("cpu:arch"), got.get("cpu:manufacturer")) == resolved


@pytest.mark.parametrize(
    "cpu,target_os",
    [
        ({"arch": "x86", "manufacturer": "amd"}, "mac"),       # every x86 Mac is Intel
        ({"arch": "x86", "manufacturer": "apple"}, "mac"),     # Apple makes no x86 CPU
        ({"arch": "x86", "manufacturer": "apple"}, "lin"),
        ({"arch": "arm", "manufacturer": "intel"}, "win"),
        ({"arch": "arm", "manufacturer": "amd"}, "lin"),
        ({"arch": "arm", "manufacturer": "broadcom"}, "win"),  # Windows on ARM is Snapdragon
        ({"arch": "arm", "manufacturer": "qualcomm"}, "mac"),
        ({"manufacturer": "qualcomm"}, "mac"),
        ({"manufacturer": "cyrix"}, "win"),
        ({"arch": "riscv"}, "lin"),
        ({"arch": "x86", "vendor": "intel"}, "win"),
        ("arm", "win"),
    ],
)
def test_impossible_machines_are_rejected(cpu, target_os):
    with pytest.raises(ValueError):
        coherence.resolve_cpu(cpu, target_os)


def test_an_os_left_open_is_drawn_among_those_with_a_gpu_for_the_cpu():
    # fpgen records Apple GPUs only on macOS and no ARM GPU on Windows, so an
    # ARM identity is a Mac or a Linux machine rendering in software.
    assert _os_for_cpu({"arch": "arm"}, None) == ["macos", "linux"]
    assert _os_for_cpu({"manufacturer": "amd"}, None) == ["windows", "linux"]
    assert _os_for_cpu({"arch": "x86"}, ["macos", "linux"]) == ["macos", "linux"]
    with pytest.raises(ValueError):
        _os_for_cpu({"manufacturer": "amd"}, "macos")
    assert _os_for_cpu({"manufacturer": "qualcomm"}, None) == "linux"


@pytest.mark.parametrize(
    "renderer,target_os,arch,maker,fits",
    [
        (APPLE, "mac", "arm", "apple", True),
        (APPLE, "mac", "x86", "intel", False),
        ("Radeon R9 200 Series, or similar", "mac", "arm", None, False),
        ("Radeon R9 200 Series, or similar", "mac", "x86", "intel", True),
        ("Intel(R) HD Graphics, or similar", "lin", "x86", "amd", False),
        ("Radeon HD 3200 Graphics, or similar", "lin", "x86", "intel", False),
        (NVIDIA, "win", "x86", "amd", True),
        (NVIDIA, "win", "arm", "qualcomm", False),   # no Snapdragon laptop has a GeForce
        ("ANGLE (Qualcomm, Adreno X1-85 GPU Direct3D11 vs_5_0 ps_5_0), or similar", "win", "arm", "qualcomm", True),
        ("V3D 4.2", "lin", "arm", "broadcom", True),
        ("V3D 4.2", "lin", "arm", "qualcomm", False),
        ("llvmpipe, or similar", "lin", "arm", "ampere", True),   # software rendering runs on any CPU
        ("llvmpipe, or similar", "lin", "x86", "amd", True),
    ],
)
def test_the_gpu_must_fit_the_cpu(renderer, target_os, arch, maker, fits):
    assert coherence.gpu_fits_cpu(renderer, target_os, arch, maker) is fits


# --- the default ---------------------------------------------------------------

def test_a_discrete_gpu_draws_firefoxs_x86_split():
    draws = [_drawn(NVIDIA, salt=salt) for salt in range(4000)]
    share = draws.count(("x86", "intel")) / len(draws)
    assert set(draws) == {("x86", "intel"), ("x86", "amd")}
    assert abs(share - X86_INTEL_SHARE) < 0.03


def test_the_draw_is_a_pure_function_of_the_identity():
    assert [_drawn(NVIDIA, salt=s) for s in range(50)] == [_drawn(NVIDIA, salt=s) for s in range(50)]


@pytest.mark.parametrize(
    "renderer,target_os,cpu",
    [
        ("ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar", "win", ("x86", "intel")),
        ("ANGLE (Intel, Intel(R) HD Graphics 400 Direct3D11 vs_5_0 ps_5_0), or similar", "win", ("x86", "intel")),
        ("Intel(R) HD Graphics, or similar", "lin", ("x86", "intel")),
        ("ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar", "win", ("x86", "amd")),
        ("Radeon HD 3200 Graphics, or similar", "lin", ("x86", "amd")),
        # every x86 Mac has an Intel CPU, whatever its GPU
        ("Radeon R9 200 Series, or similar", "mac", ("x86", "intel")),
        ("Intel(R) HD Graphics 400, or similar", "mac", ("x86", "intel")),
        (APPLE, "mac", ("arm", "apple")),
        ("V3D 4.2", "lin", ("arm", "broadcom")),
        ("Mali-G610", "lin", ("arm", None)),   # several SoC makers ship Mali
    ],
)
def test_the_gpu_decides_the_cpu(renderer, target_os, cpu):
    assert {_drawn(renderer, target_os, salt) for salt in range(200)} == {cpu}


@pytest.mark.parametrize("cores", [10, 14, 18, 22, 28])
def test_a_core_count_only_intel_ships_decides_the_x86_vendor(cores):
    assert {_drawn(NVIDIA, salt=salt, cores=cores) for salt in range(200)} == {("x86", "intel")}


def test_an_intel_only_core_count_says_nothing_about_arm():
    # An M4 Pro reports 14.
    assert _drawn(APPLE, "mac", cores=14) == ("arm", "apple")
    config = {"cpu:arch": "arm", "cpu:manufacturer": "apple", "webGl:renderer": APPLE,
              "navigator.hardwareConcurrency": 14}
    assert coherence.cpu_conflict(config, "mac") is None


def test_a_core_count_both_vendors_ship_leaves_the_draw_open():
    assert {_drawn(NVIDIA, salt=salt, cores=16) for salt in range(200)} == {("x86", "intel"), ("x86", "amd")}


def test_a_callers_cpu_is_kept():
    config = {"cpu:arch": "x86", "cpu:manufacturer": "amd", "webGl:renderer": NVIDIA}
    set_cpu_default(config, "win")
    assert (config["cpu:arch"], config["cpu:manufacturer"]) == ("x86", "amd")


# --- coherence -------------------------------------------------------------------

def test_coherence_repairs_a_cpu_the_gpu_contradicts():
    config = {"cpu:arch": "x86", "cpu:manufacturer": "amd", "webGl:renderer": "Intel(R) HD Graphics, or similar"}
    coherence.apply(config, "lin")
    assert (config["cpu:arch"], config["cpu:manufacturer"]) == ("x86", "intel")
    config = {"cpu:arch": "x86", "cpu:manufacturer": "intel", "webGl:renderer": APPLE}
    coherence.apply(config, "mac")
    assert (config["cpu:arch"], config["cpu:manufacturer"]) == ("arm", "apple")


def test_coherence_keeps_and_reports_a_callers_cpu():
    config = {"cpu:arch": "x86", "cpu:manufacturer": "amd", "webGl:renderer": "Intel(R) HD Graphics, or similar"}
    left = coherence.apply(config, "lin", keep=frozenset({"cpu:arch", "cpu:manufacturer"}))
    assert config["cpu:manufacturer"] == "amd"
    assert [v.rule for v in left] == ["cpu-matches-hardware"]


def test_coherence_repairs_an_x86_vendor_its_core_count_contradicts():
    config = {"cpu:arch": "x86", "cpu:manufacturer": "amd", "webGl:renderer": NVIDIA,
              "navigator.hardwareConcurrency": 22}
    assert [v.rule for v in coherence.validate(config, "win")] == ["cpu-matches-hardware"]
    coherence.apply(config, "win")
    assert config["cpu:manufacturer"] == "intel"


def test_the_gpu_decides_before_the_core_count():
    amd_apu = "Radeon HD 3200 Graphics, or similar"
    assert _drawn(amd_apu, "lin", cores=14) == ("x86", "amd")


# --- the pref ----------------------------------------------------------------------

def test_the_pref_values_are_the_patchs():
    # CPU_IDENTITY_* in cpu-identity.patch (mozilla/CpuIdentity.h)
    assert LAUNCHER_CONSTANTS["cpuIdentityPref"] == {"x86/intel": 1, "x86/amd": 2, "arm": 3}
    assert cpu_identity_pref({"cpu:arch": "x86", "cpu:manufacturer": "intel"}) == 1
    assert cpu_identity_pref({"cpu:arch": "x86", "cpu:manufacturer": "amd"}) == 2
    assert cpu_identity_pref({"cpu:arch": "arm", "cpu:manufacturer": "apple"}) == 3
    assert cpu_identity_pref({"cpu:arch": "arm"}) == 3
    assert cpu_identity_pref({}) == 0


def test_vpx_is_realtime_only_on_arm_windows_and_linux():
    # Mozilla configures libvpx --enable-realtime-only for win/aarch64 and
    # linux/arm64, not mac/arm64 (media/libvpx/generate_sources_mozbuild.sh)
    arm = {"cpu:arch": "arm", "cpu:manufacturer": "qualcomm"}
    assert vpx_realtime_only(arm, "win") and vpx_realtime_only(arm, "lin")
    assert not vpx_realtime_only({"cpu:arch": "arm", "cpu:manufacturer": "apple"}, "mac")
    for os_ in ("win", "lin", "mac"):
        assert not vpx_realtime_only({"cpu:arch": "x86", "cpu:manufacturer": "amd"}, os_)
    assert not vpx_realtime_only({}, "lin")
