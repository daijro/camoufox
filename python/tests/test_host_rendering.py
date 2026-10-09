"""The canvas renders on the host: an identity on the host's OS claims the
host's GPU, and one on another OS gets the canvas placeholder.

Run with:
    cd python && python -m pytest tests/test_host_rendering.py -v
"""

import os
import re
import sys
import warnings
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import orjson  # noqa: E402
import pytest  # noqa: E402

from camoufox import sync_api, utils  # noqa: E402
from camoufox._warnings import LeakWarning  # noqa: E402
from camoufox.host_rendering import (  # noqa: E402
    BASELINE_OVERRIDES_PREF,
    CANVAS_PLACEHOLDER_TARGETS,
    FEATURE_BLOCKED_DEVICE,
    WEBGPU_BLOCKLIST_PREF,
    has_canvas_placeholder,
    host_gpu,
)

HOST_GPU = ("AMD", "Radeon HD 3200 Graphics, or similar")
OTHER_GPU = ("NVIDIA Corporation", "GeForce GTX 980, or similar")
SOFTWARE_GPU = ("Mesa", "llvmpipe, or similar")
WINDOWS_GPU = ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar")
WINDOWS_SOFTWARE_GPU = (
    "Google Inc. (Microsoft)",
    "ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0), or similar",
)


@contextmanager
def on_host(gpu, os_key="lin"):
    """A host whose Firefox renders on `gpu`; records every probe."""
    probes = []

    def probe(executable_path, headless, env):
        probes.append((executable_path, headless))
        return gpu

    with mock.patch.object(utils, "_host_os_key", lambda: os_key), mock.patch.object(
        utils, "host_gpu", probe
    ), mock.patch.object(utils, "has_display", lambda env: False), mock.patch.object(
        utils, "installed_verstr", lambda: "150.0.2"
    ), mock.patch.object(utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox"):
        yield probes


def launch(**kwargs):
    kwargs.setdefault("i_know_what_im_doing", True)
    options = utils.launch_options(**kwargs)
    env = options["env"]
    chunks = sorted(
        (int(k.rsplit("_", 1)[1]), v) for k, v in env.items() if k.startswith("CAMOU_CONFIG_")
    )
    config = orjson.loads("".join(chunk for _, chunk in chunks))
    return options, config


def placeholder(options):
    return has_canvas_placeholder(options["firefox_user_prefs"])


def webgpu(options):
    """(navigator.gpu exposed, requestAdapter() blocked) for these launch options."""
    prefs = options["firefox_user_prefs"]
    return prefs["dom.webgpu.enabled"], prefs.get(WEBGPU_BLOCKLIST_PREF) == FEATURE_BLOCKED_DEVICE


class TestHostOs:
    def test_a_drawn_identity_claims_the_host_gpu_without_noise(self):
        with on_host(HOST_GPU) as probes:
            options, config = launch(os="linux")

        assert (config["webGl:vendor"], config["webGl:renderer"]) == HOST_GPU
        assert not placeholder(options)
        assert probes == [("/nonexistent/camoufox", False)]

    def test_a_software_renderer_leaves_the_gpu_to_the_draw(self):
        with on_host(SOFTWARE_GPU):
            options, config = launch(os="linux")

        assert "llvmpipe" not in config["webGl:renderer"]
        assert not placeholder(options)

    def test_a_host_gpu_fpgen_never_recorded_is_not_claimed(self):
        unrecorded = ("AMD", "Radeon Unrecorded, or similar")
        with on_host(unrecorded):
            _, config = launch(os="linux")

        assert (config["webGl:vendor"], config["webGl:renderer"]) != unrecorded

    def test_a_pinned_gpu_is_kept_without_a_probe(self):
        with on_host(HOST_GPU) as probes:
            _, config = launch(os="linux", webgl_config=OTHER_GPU)

        assert (config["webGl:vendor"], config["webGl:renderer"]) == OTHER_GPU
        assert probes == []

    def test_noise_on_request_needs_no_probe(self):
        with on_host(HOST_GPU) as probes:
            options, _ = launch(os="linux", canvas_noise=True)

        assert placeholder(options)
        assert probes == []


class TestAnotherOs:
    def test_the_canvas_is_covered_without_a_probe(self):
        with on_host(HOST_GPU) as probes:
            options, _ = launch(os="windows")

        assert placeholder(options)
        assert probes == []

    def test_covering_the_canvas_warns(self):
        with on_host(HOST_GPU), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            launch(os="windows", i_know_what_im_doing=False)

        assert any(
            issubclass(w.category, LeakWarning) and "canvas_noise=False" in str(w.message) for w in caught
        )

    def test_it_can_be_turned_off(self):
        with on_host(HOST_GPU):
            options, _ = launch(os="windows", canvas_noise=False)

        assert not placeholder(options)

    def test_caller_overrides_are_kept(self):
        with on_host(HOST_GPU):
            options, _ = launch(
                os="windows", firefox_user_prefs={BASELINE_OVERRIDES_PREF: "-MaxTouchPointsCollapse"}
            )

        assert options["firefox_user_prefs"][BASELINE_OVERRIDES_PREF] == ",".join(
            ("-MaxTouchPointsCollapse", *CANVAS_PLACEHOLDER_TARGETS)
        )


class TestWebGpu:
    """navigator.gpu where Firefox on the claimed device has it; the host's
    adapter only behind the host's own GPU, otherwise null as when blocklisted."""

    def test_the_host_gpu_on_windows_keeps_its_adapter(self):
        with on_host(WINDOWS_GPU, "win"):
            options, config = launch(os="windows")

        assert (config["webGl:vendor"], config["webGl:renderer"]) == WINDOWS_GPU
        assert webgpu(options) == (True, False)

    def test_software_rendering_on_windows_has_no_adapter(self):
        with on_host(WINDOWS_SOFTWARE_GPU, "win"):
            options, _ = launch(os="windows")

        assert webgpu(options) == (True, True)

    def test_windows_on_another_host_has_no_adapter(self):
        with on_host(HOST_GPU):
            options, _ = launch(os="windows")

        assert webgpu(options) == (True, True)

    def test_a_pinned_gpu_has_no_adapter(self):
        with on_host(WINDOWS_GPU, "win"):
            options, _ = launch(os="windows", webgl_config=WINDOWS_SOFTWARE_GPU)

        assert webgpu(options) == (True, True)

    def test_caller_prefs_are_kept(self):
        with on_host(HOST_GPU):
            options, _ = launch(os="linux", firefox_user_prefs={"dom.webgpu.enabled": True})

        assert webgpu(options) == (True, False)

    def test_linux_has_no_navigator_gpu(self):
        with on_host(HOST_GPU):
            options, _ = launch(os="linux")

        assert webgpu(options) == (False, False)

    @pytest.mark.parametrize(
        "gpu, exposed",
        [(("Apple", "Apple M1, or similar"), True), (("Intel Inc.", "Intel(R) HD Graphics, or similar"), False)],
    )
    def test_macos_has_navigator_gpu_on_apple_silicon_only(self, gpu, exposed):
        with on_host(HOST_GPU):
            options, _ = launch(os="macos", webgl_config=gpu)

        assert webgpu(options) == (exposed, exposed)


def test_the_probe_ignores_what_the_launcher_adds_to_the_environment():
    """host_identity probes with the launch's env, which carries
    CAMOU_* and FONTCONFIG_FILE; that must hit launch_options' cached probe."""
    from camoufox import host_rendering

    with mock.patch.object(host_rendering, "_host_gpu", return_value=HOST_GPU) as probe:
        host_gpu("/bin/camoufox", True, {"DISPLAY": ":0"})
        host_gpu("/bin/camoufox", True, {"DISPLAY": ":0", "CAMOU_CONFIG_1": "{}", "FONTCONFIG_FILE": "/x"})

    assert probe.call_args_list[0] == probe.call_args_list[1]


def browser_on_host(gpu):
    browser = mock.MagicMock()
    browser.version = "150.0.2"
    browser._camoufox_host_identity = ("lin", gpu)
    return browser


def renderer_of(context):
    script = context.add_init_script.call_args.args[0]
    return re.search(r'setWebGLRenderer\("([^"]+)"\)', script).group(1)


class TestContextsOfAHostBrowser:
    def test_a_context_claims_the_host_os_and_gpu(self):
        browser = browser_on_host(HOST_GPU)
        sync_api.NewContext(browser)

        script = browser.new_context.return_value.add_init_script.call_args.args[0]
        assert 'setNavigatorPlatform("Linux' in script
        assert renderer_of(browser.new_context.return_value) == HOST_GPU[1]

    def test_a_software_host_leaves_the_gpu_to_the_draw(self):
        browser = browser_on_host(None)
        sync_api.NewContext(browser)

        assert "llvmpipe" not in renderer_of(browser.new_context.return_value)

    def test_another_os_raises(self):
        with pytest.raises(ValueError, match="canvas_noise=True"):
            sync_api.NewContext(browser_on_host(HOST_GPU), os="windows")

    def test_a_preset_with_another_gpu_raises(self):
        preset = {
            "navigator": {"platform": "Linux x86_64"},
            "webgl": {"unmaskedVendor": OTHER_GPU[0], "unmaskedRenderer": OTHER_GPU[1]},
        }
        with pytest.raises(ValueError, match="canvas_noise=True"):
            sync_api.NewContext(browser_on_host(HOST_GPU), preset=preset)


class TestHostIdentity:
    def attach(self, noised, canvas_noise):
        prefs = {}
        if noised:
            prefs[BASELINE_OVERRIDES_PREF] = ",".join(CANVAS_PLACEHOLDER_TARGETS)
        options = {"executable_path": "/nonexistent/camoufox", "headless": True, "env": {}, "firefox_user_prefs": prefs}
        with mock.patch.object(utils, "_host_os_key", lambda: "lin"), mock.patch.object(
            utils, "host_gpu", lambda *args: HOST_GPU
        ):
            return utils.host_identity(options, canvas_noise)

    def test_a_browser_without_noise_records_the_host(self):
        assert self.attach(False, None) == ("lin", HOST_GPU)

    def test_a_noised_browser_records_nothing(self):
        assert self.attach(True, None) is None

    @pytest.mark.parametrize("canvas_noise", [False, True])
    def test_a_callers_explicit_choice_records_nothing(self, canvas_noise):
        assert self.attach(False, canvas_noise) is None
