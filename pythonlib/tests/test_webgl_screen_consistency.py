"""
Tests for the WebGL <-> screen coherence helpers in camoufox.fingerprints.

Run with:
    cd pythonlib && python -m pytest tests/test_webgl_screen_consistency.py -v

The regression these guard (daijro/camoufox#729): BrowserForge picks the
screen, webgl_data.db picks the GPU, and nothing ties them together -- so the
synthetic path can emit pairs no real machine ships (a discrete GPU behind a
1024x600 netbook panel).

The constraint has to be read through Gecko's renderer sanitizer
(dom/canvas/SanitizeRenderer.cpp), which collapses every renderer string into
one of ~11 device buckets before a page sees it. Two things follow, and most
of these tests exist to pin them down: raw model names never reach the page,
and a bucket spanning a desktop RTX 4090 and a mobile GTX 1650 Max-Q cannot
carry a 1080p floor.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import fingerprints  # noqa: E402
from camoufox.fingerprints import (  # noqa: E402
    MODERN_SCREEN_FLOOR,
    _renderer_bucket,
    gpu_screen_is_plausible,
    is_software_renderer,
    raise_screen_to_modern_floor,
    sample_webgl_for_screen,
)

# The three spellings Gecko emits for one discrete-NVIDIA bucket.
_NV_ANGLE = "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"
_NV_PCIE = "NVIDIA GeForce GTX 980/PCIe/SSE2"
_NV_NOUVEAU = "GeForce GTX 980, or similar"

_AMD_IGP = "ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar"
_INTEL = "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar"
_APPLE = "Apple M1, or similar"
_LLVMPIPE = "llvmpipe, or similar"


# -- bucket reduction --------------------------------------------------------


@pytest.mark.parametrize("renderer", [_NV_ANGLE, _NV_PCIE, _NV_NOUVEAU])
def test_every_spelling_of_one_gpu_reduces_to_one_bucket(renderer):
    # ANGLE wrapping, the /PCIe/SSE2 suffix and nouveau's missing "NVIDIA "
    # prefix are the same GPU class. Matching raw substrings put these on
    # three different rules, so the same hardware got three different floors.
    assert _renderer_bucket(renderer) == "GeForce GTX 980"


def test_angle_vendor_field_does_not_decide_the_bucket():
    # Regression: matching the substring "ANGLE (AMD" gave this integrated
    # chipset a discrete-GPU floor, while its Linux spelling got none.
    assert _renderer_bucket(_AMD_IGP) == "Radeon HD 3200 Graphics"
    assert _renderer_bucket("Radeon HD 3200 Graphics, or similar") == (
        "Radeon HD 3200 Graphics"
    )


def test_angle_vulkan_form_is_unwrapped():
    assert _renderer_bucket("ANGLE (Samsung Xclipse 920) on Vulkan") == (
        "Samsung Xclipse 920"
    )


# -- what the table constrains ----------------------------------------------


@pytest.mark.parametrize("renderer", [_NV_ANGLE, _NV_PCIE, _NV_NOUVEAU])
def test_discrete_gpu_rejected_on_a_netbook_screen(renderer):
    assert not gpu_screen_is_plausible(renderer, 1024, 600)


@pytest.mark.parametrize(
    "width,height", [(1024, 768), (1280, 720), (1280, 800), (1366, 768), (1920, 1080)]
)
def test_discrete_gpu_accepted_on_any_real_laptop_panel(width, height):
    # A 1366x768 laptop with a discrete NVIDIA GPU is ordinary hardware, and
    # "GeForce GTX 980, or similar" is the bucket a mobile GTX 1650 Max-Q
    # reports. Anything stricter rejects real machines.
    assert gpu_screen_is_plausible(_NV_ANGLE, width, height)


def test_the_floor_is_an_area_not_a_per_axis_bound():
    # 1280x800 and 1366x768 are both ordinary panels and neither dominates the
    # other, so a per-axis floor taken from one throws out the other.
    assert gpu_screen_is_plausible(_NV_ANGLE, 1280, 800)
    assert gpu_screen_is_plausible(_NV_ANGLE, 1366, 768)


@pytest.mark.parametrize("width,height", [(1024, 600), (800, 480), (1024, 576)])
def test_discrete_gpu_rejected_on_netbook_panels(width, height):
    assert not gpu_screen_is_plausible(_NV_ANGLE, width, height)


def test_integrated_parts_are_not_floored():
    # Gecko's "Intel(R) HD Graphics" bucket swallows the GMA 3150 netbook
    # chipset, and "Radeon HD 3200 Graphics" is its catch-all for a bare
    # "AMD"/"Radeon" -- including netbook APUs. Neither carries a floor.
    assert gpu_screen_is_plausible(_INTEL, 1024, 600)
    assert gpu_screen_is_plausible(_AMD_IGP, 1024, 600)


def test_apple_silicon_is_not_pinned_to_retina():
    # Apple silicon also ships in the Mac mini / Mac Studio, which drive
    # whatever external monitor is attached.
    assert gpu_screen_is_plausible(_APPLE, 1920, 1080)
    assert gpu_screen_is_plausible(_APPLE, 1280, 800)


def test_raw_model_names_are_out_of_scope():
    # Firefox never reports these: SanitizeRenderer turns an RTX 3070 into
    # "GeForce GTX 980" and a UHD 620 into "Intel(R) HD Graphics 400" before
    # the page sees anything. Keying on them was matching nothing.
    assert gpu_screen_is_plausible(
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)", 1024, 600
    )


def test_missing_values_are_not_constrained():
    assert gpu_screen_is_plausible(None, 1920, 1080)
    assert gpu_screen_is_plausible(_NV_ANGLE, None, None)


# -- software rasterizers ----------------------------------------------------


@pytest.mark.parametrize(
    "renderer",
    [
        _LLVMPIPE,
        "ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)",
        "Generic Renderer",
    ],
)
def test_software_renderers_are_unconstrained(renderer):
    # A VM reports whatever the window manager hands it.
    assert is_software_renderer(renderer)
    assert gpu_screen_is_plausible(renderer, 1024, 600)


def test_hardware_is_not_mistaken_for_software(monkeypatch):
    for renderer in (_NV_ANGLE, _INTEL, _APPLE, _AMD_IGP):
        assert not is_software_renderer(renderer)


def test_software_first_draw_is_never_resampled(monkeypatch):
    """The strongest reason this sampler must not be a plain reject loop.

    Rejecting hardware draws while accepting every software one renormalises
    the pool onto llvmpipe / WARP / SwiftShader. On a sub-floor screen that
    turned a 1.5% software rate into ~40%, trading a weak incoherence for the
    strongest VM/headless tell there is. So the first draw settles the class.
    """
    draws = iter([{"webGl:renderer": _LLVMPIPE}, {"webGl:renderer": _INTEL}])
    monkeypatch.setattr(fingerprints, "sample_webgl", lambda *a, **kw: next(draws))

    # 1024x600 would reject a discrete GPU, but llvmpipe is plausible there and
    # must be returned as drawn rather than swapped for the Intel part.
    assert sample_webgl_for_screen("lin", 1024, 600)["webGl:renderer"] == _LLVMPIPE


def test_software_draws_are_skipped_when_resampling(monkeypatch):
    # A hardware first draw settles the class as hardware, so a software
    # candidate mid-loop is skipped instead of accepted -- otherwise the
    # rejection loop still leaks probability mass onto the rasterizers.
    draws = iter(
        [
            {"webGl:renderer": _NV_ANGLE},  # implausible at 1024x600
            {"webGl:renderer": _LLVMPIPE},  # plausible, but wrong class
            {"webGl:renderer": _INTEL},  # the coherent hardware answer
        ]
    )
    monkeypatch.setattr(fingerprints, "sample_webgl", lambda *a, **kw: next(draws))

    assert sample_webgl_for_screen("lin", 1024, 600)["webGl:renderer"] == _INTEL


def test_falls_back_to_the_first_draw_when_nothing_is_coherent(monkeypatch):
    monkeypatch.setattr(
        fingerprints, "sample_webgl", lambda *a, **kw: {"webGl:renderer": _NV_ANGLE}
    )
    fp = sample_webgl_for_screen("win", 800, 600, attempts=4)
    assert fp["webGl:renderer"] == _NV_ANGLE


def test_a_plausible_first_draw_costs_one_query(monkeypatch):
    # sample_webgl opens a fresh sqlite connection per call, and the common
    # case (any screen at or above the floor) must not pay for 32 of them.
    calls = []

    def _counted(*args, **kwargs):
        calls.append(args)
        return {"webGl:renderer": _NV_ANGLE}

    monkeypatch.setattr(fingerprints, "sample_webgl", _counted)
    sample_webgl_for_screen("win", 1920, 1080)
    assert len(calls) == 1


@pytest.mark.parametrize("target_os", ["win", "mac", "lin"])
def test_sampled_gpu_is_coherent_with_the_screen(target_os):
    # Against the real webgl_data.db pool.
    for _ in range(25):
        fp = sample_webgl_for_screen(target_os, 1280, 800)
        assert gpu_screen_is_plausible(fp.get("webGl:renderer"), 1280, 800)


# -- the screen floor --------------------------------------------------------


def test_screen_floor_lifts_netbook_geometry():
    config = {
        "screen.width": 1024,
        "screen.height": 600,
        "screen.availWidth": 1024,
        "screen.availHeight": 560,
    }
    raise_screen_to_modern_floor(config)
    assert (config["screen.width"], config["screen.height"]) == MODERN_SCREEN_FLOOR
    # The taskbar gap has to survive, or fix_screen_no_taskbar's invariant --
    # and CreepJS's noTaskbar check -- breaks.
    assert config["screen.height"] - config["screen.availHeight"] == 40
    assert config["screen.width"] - config["screen.availWidth"] == 0
    assert config["screen.availHeight"] < config["screen.height"]


def test_screen_floor_leaves_an_adequate_screen_alone():
    config = {
        "screen.width": 1920,
        "screen.height": 1080,
        "screen.availWidth": 1920,
        "screen.availHeight": 1040,
    }
    before = dict(config)
    raise_screen_to_modern_floor(config)
    assert config == before


def test_screen_floor_is_a_no_op_without_screen_values():
    config = {}
    raise_screen_to_modern_floor(config)
    assert config == {}


# -- the two entry points must agree ----------------------------------------


@pytest.mark.parametrize("target_os", ["windows", "macos", "linux"])
def test_context_fingerprints_get_the_same_treatment(target_os):
    """generate_context_fingerprint() is the per-context API #729 names, and
    build-tester drives the browser through it. It sampled the GPU with a bare
    sample_webgl() and never applied the floor, so the coherence fix reached
    launch_options() only."""
    from camoufox.fingerprints import generate_context_fingerprint

    for _ in range(15):
        config = generate_context_fingerprint(os=target_os)["config"]
        renderer = config.get("webGl:renderer")
        width, height = config.get("screen.width"), config.get("screen.height")
        assert renderer and width and height
        assert gpu_screen_is_plausible(renderer, width, height)
        assert width * height > 1024 * 600


def test_preset_screens_are_never_lifted():
    """Presets are real devices, coherent by construction -- #729 says so
    explicitly. Two bundled v150 presets report genuinely sub-netbook screens,
    and the floor used to rewrite them to 1366x768 because
    _user_set_screen_window is computed before the preset merges in."""
    import json
    from pathlib import Path

    from camoufox.utils import launch_options

    presets = json.loads(
        (Path(__file__).parent.parent / "camoufox" / "fingerprint-presets-v150.json").read_text()
    )

    def small_presets(node):
        if isinstance(node, dict):
            screen = node.get("screen")
            if (
                isinstance(screen, dict)
                and screen.get("width")
                and screen.get("height")
                and screen["width"] * screen["height"] <= 1024 * 600
            ):
                yield node
            for value in node.values():
                yield from small_presets(value)
        elif isinstance(node, list):
            for value in node:
                yield from small_presets(value)

    found = list(small_presets(presets))
    assert found, "expected the v150 presets to still carry sub-netbook screens"

    for preset in found:
        env = launch_options(
            headless=True, fingerprint_preset=preset, i_know_what_im_doing=True
        )["env"]
        raw = "".join(
            env[k]
            for k in sorted(
                (k for k in env if k.startswith("CAMOU_CONFIG_")),
                key=lambda k: int(k.rsplit("_", 1)[1]),
            )
        )
        config = json.loads(raw)
        assert (config["screen.width"], config["screen.height"]) == (
            preset["screen"]["width"],
            preset["screen"]["height"],
        )


@pytest.mark.parametrize("ff_version", ["148", "152"])
@pytest.mark.parametrize(
    "target_os,webgl_os",
    [("windows", "win"), ("macos", "mac"), ("linux", "lin")],
)
def test_random_preset_pool_only_contains_supported_webgl_pairs(
    monkeypatch, ff_version, target_os, webgl_os
):
    """Every preset eligible for random selection must survive launch_options.

    The bundled preset files contain vendor/renderer pairs absent from
    webgl_data.db. Selection therefore failed only when random.choice happened
    to pick one of those entries, making browser startup intermittently crash.
    """
    from camoufox.fingerprints import get_random_preset
    from camoufox.webgl import sample_webgl

    candidates = []

    def capture(pool):
        candidates.extend(pool)
        return pool[0]

    monkeypatch.setattr(fingerprints, "choice", capture)
    get_random_preset(os=target_os, ff_version=ff_version)

    assert candidates
    for preset in candidates:
        webgl = preset.get("webgl", {})
        vendor = webgl.get("unmaskedVendor")
        renderer = webgl.get("unmaskedRenderer")
        if vendor and renderer:
            sample_webgl(webgl_os, vendor, renderer)
