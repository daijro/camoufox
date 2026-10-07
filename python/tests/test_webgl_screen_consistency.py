"""
Tests for the WebGL <-> screen coherence helpers in camoufox.fingerprints.

Run with:
    cd python && python -m pytest tests/test_webgl_screen_consistency.py -v

The regression these guard (daijro/camoufox#729): the generator picks the
screen, camoufox.webgl picks the GPU, and nothing ties them together -- so the
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from camoufox.fingerprints import (  # noqa: E402
    MODERN_SCREEN_FLOOR,
    _renderer_bucket,
    gpu_screen_is_plausible,
    is_software_renderer,
    raise_screen_to_modern_floor,
)
from camoufox.webgl import sample_webgl_for_screen  # noqa: E402

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


@pytest.mark.parametrize("target_os", ["win", "mac", "lin"])
def test_sampled_gpu_is_coherent_with_the_screen(target_os):
    for seed in range(25):
        fp = sample_webgl_for_screen(target_os, 1280, 800, seed=seed)
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
    build-tester drives the browser through it. It drew the GPU without the
    screen and never applied the floor, so the coherence fix reached
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
    """A preset's own small screen is kept -- #729 -- unless it is not a screen.

    The original premise here was that a preset IS a real device, so the floor
    must never rewrite it. That premise does not survive the data: the two
    "genuinely sub-netbook" v150 presets report 736x414 (an iPhone viewport) and
    960x540, and another reports 1440x2560, portrait. The presets are scraped
    from live traffic, so they carry phones and bots alongside real desktops.

    So the rule is narrower than "never lift a preset screen": a panel a desktop
    could have is kept at whatever size it claims, and one no desktop reports is
    repaired (camoufox.coherence). This asserts the keeping half; the repairing
    half is in test_coherence.py."""
    import json
    from pathlib import Path

    from camoufox.utils import launch_options

    presets = json.loads(
        (Path(__file__).parent.parent / "src" / "camoufox" / "fingerprint-presets-v150.json").read_text()
    )

    def small_presets(node):
        if isinstance(node, dict):
            screen = node.get("screen")
            if (
                isinstance(screen, dict)
                and screen.get("width")
                and screen.get("height")
                # Small, but a shape a desktop can have: coherence.py repairs
                # anything narrower than 1024 or taller than it is wide.
                and screen["width"] * screen["height"] <= 1366 * 768
                and screen["width"] >= 1024
                and screen["width"] >= screen["height"]
            ):
                yield node
            for value in node.values():
                yield from small_presets(value)
        elif isinstance(node, list):
            for value in node:
                yield from small_presets(value)

    found = list(small_presets(presets))
    assert found, "expected the v150 presets to still carry small desktop screens"

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
