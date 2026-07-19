"""Regression tests for per-launch environment isolation."""

import os

import pytest

from camoufox import utils


@pytest.fixture
def isolated_launch_dependencies(monkeypatch):
    """Keep launch_options focused on environment assembly, without a browser."""
    monkeypatch.setattr(utils, "add_default_addons", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "generate_fingerprint", lambda *args, **kwargs: object())
    monkeypatch.setattr(utils, "from_browserforge", lambda *args, **kwargs: {})
    monkeypatch.setattr(utils, "get_screen_cons", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "_generate_random_font_subset", lambda *args: [])
    monkeypatch.setattr(utils, "_generate_random_voice_subset", lambda *args: [])
    monkeypatch.setattr(utils, "fix_navigator_arch", lambda *args: None)
    monkeypatch.setattr(utils, "fix_screen_no_taskbar", lambda *args: None)
    monkeypatch.setattr(utils, "clamp_window_dimensions", lambda *args: None)
    monkeypatch.setattr(utils, "set_media_devices_defaults", lambda *args: None)
    monkeypatch.setattr(utils, "installed_verstr", lambda: "152.0.4-beta.28")
    monkeypatch.setattr(utils, "validate_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "get_env_vars", lambda *args, **kwargs: {})
    monkeypatch.setattr(utils, "launch_path", lambda: "/test/camoufox")


def _launch_with_virtual_display(**kwargs):
    return utils.launch_options(
        virtual_display=":4242",
        headless=True,
        block_webgl=True,
        i_know_what_im_doing=True,
        **kwargs,
    )


def test_virtual_display_does_not_mutate_process_environment(
    monkeypatch, isolated_launch_dependencies
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("GDK_BACKEND", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("MOZ_ENABLE_WAYLAND", "1")
    keys = ("DISPLAY", "GDK_BACKEND", "WAYLAND_DISPLAY", "MOZ_ENABLE_WAYLAND")
    before = {key: os.environ.get(key) for key in keys}

    options = _launch_with_virtual_display()

    assert {key: os.environ.get(key) for key in keys} == before
    assert options["env"]["DISPLAY"] == ":4242"
    assert options["env"]["GDK_BACKEND"] == "x11"
    assert "WAYLAND_DISPLAY" not in options["env"]
    assert options["env"]["MOZ_ENABLE_WAYLAND"] == "0"


def test_virtual_display_does_not_mutate_caller_environment(
    isolated_launch_dependencies,
):
    caller_env = {
        "UNCHANGED": "value",
        "GDK_BACKEND": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "MOZ_ENABLE_WAYLAND": "1",
    }
    before = caller_env.copy()

    options = _launch_with_virtual_display(env=caller_env)

    assert caller_env == before
    assert options["env"]["UNCHANGED"] == "value"
    assert options["env"]["DISPLAY"] == ":4242"
    assert options["env"]["GDK_BACKEND"] == "x11"
    assert "WAYLAND_DISPLAY" not in options["env"]
    assert options["env"]["MOZ_ENABLE_WAYLAND"] == "0"
