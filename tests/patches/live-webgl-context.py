"""
Opt-in live browser readback for per-context WebGL spoofing.

Run directly:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib \
    python3 tests/patches/live-webgl-context.py

Or with pytest:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib \
    python3 -m pytest --confcutdir=tests/patches tests/patches/live-webgl-context.py
"""

import json
import os
from urllib.parse import quote

from camoufox.sync_api import NewContext
from camoufox.utils import get_env_vars
from playwright.sync_api import sync_playwright


HTML = """<!doctype html><meta charset="utf-8"><pre id="out"></pre><script>
function readWebGL() {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
  if (!gl) return null;
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  if (!ext) return null;
  return {
    vendor: gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),
    renderer: gl.getParameter(ext.UNMASKED_RENDERER_WEBGL),
  };
}
document.getElementById('out').textContent = JSON.stringify({
  setters: [typeof window.setWebGLVendor, typeof window.setWebGLRenderer],
  webgl: readWebGL(),
});
</script>"""

URL = "data:text/html;charset=utf-8," + quote(HTML)


def _required_executable():
    path = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
    if path:
        return path
    try:
        import pytest

        pytest.skip("CAMOUFOX_EXECUTABLE_PATH is required for live browser checks")
    except ImportError:
        raise RuntimeError("CAMOUFOX_EXECUTABLE_PATH is required") from None


def _read_page(page):
    page.goto(URL)
    page.wait_for_function(
        "document.querySelector('#out').textContent.length > 0",
        timeout=5000,
    )
    return json.loads(page.locator("#out").text_content(timeout=5000))


def _read_context(browser, vendor, renderer):
    context = browser.new_context()
    context.add_init_script(
        f"""(() => {{
          if (typeof window.setWebGLVendor === "function") {{
            window.setWebGLVendor({json.dumps(vendor)});
          }}
          if (typeof window.setWebGLRenderer === "function") {{
            window.setWebGLRenderer({json.dumps(renderer)});
          }}
        }})()"""
    )
    try:
        page = context.new_page()
        try:
            return _read_page(page)
        finally:
            page.close()
    finally:
        context.close()


def test_context_webgl_vendor_renderer_are_isolated_and_reusable():
    executable_path = _required_executable()
    vendor_a = "Vulpine Test Vendor A"
    renderer_a = "Vulpine Test Renderer A"
    vendor_b = "Vulpine Test Vendor B"
    renderer_b = "Vulpine Test Renderer B"

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(
            executable_path=executable_path,
            headless=True,
            firefox_user_prefs={
                "webgl.force-enabled": True,
            },
        )
        try:
            first_a = _read_context(browser, vendor_a, renderer_a)
            first_b = _read_context(browser, vendor_b, renderer_b)
            second_a = _read_context(browser, vendor_a, renderer_a)
        finally:
            browser.close()

    assert first_a["webgl"] == {"vendor": vendor_a, "renderer": renderer_a}
    assert first_b["webgl"] == {"vendor": vendor_b, "renderer": renderer_b}
    assert second_a["webgl"] == {"vendor": vendor_a, "renderer": renderer_a}
    assert first_a["webgl"] != first_b["webgl"]


def test_context_webgl_overrides_launch_config_webgl():
    executable_path = _required_executable()
    parent_vendor = "Vulpine Parent Vendor"
    parent_renderer = "Vulpine Parent Renderer"
    context_vendor = "Vulpine Context Vendor"
    context_renderer = "Vulpine Context Renderer"

    env = {
        **os.environ,
        **get_env_vars(
            {
                "webGl:vendor": parent_vendor,
                "webGl:renderer": parent_renderer,
            },
            "mac",
        ),
    }
    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(
            executable_path=executable_path,
            headless=True,
            env=env,
            firefox_user_prefs={
                "webgl.force-enabled": True,
            },
        )
        try:
            context_result = _read_context(
                browser,
                context_vendor,
                context_renderer,
            )
        finally:
            browser.close()

    assert context_result["webgl"] == {
        "vendor": context_vendor,
        "renderer": context_renderer,
    }


def _preset(vendor, renderer, platform="Win32", cores=8):
    return {
        "navigator": {
            "userAgent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
                "Gecko/20100101 Firefox/146.0"
            ),
            "platform": platform,
            "hardwareConcurrency": cores,
            "oscpu": "Windows NT 10.0; Win64; x64",
            "maxTouchPoints": 0,
        },
        "screen": {
            "width": 1366,
            "height": 768,
            "colorDepth": 24,
            "availWidth": 1366,
            "availHeight": 728,
        },
        "webgl": {
            "unmaskedVendor": vendor,
            "unmaskedRenderer": renderer,
        },
        "fonts": ["Arial", "Segoe UI"],
        "speechVoices": ["Microsoft David"],
    }


def _read_new_context(browser, vendor, renderer):
    context = NewContext(browser, preset=_preset(vendor, renderer), ff_version="146")
    try:
        page = context.new_page()
        try:
            return _read_page(page)
        finally:
            page.close()
    finally:
        context.close()


def test_new_context_applies_preset_webgl_vendor_renderer():
    executable_path = _required_executable()
    vendor_a = "Vulpine Preset Vendor A"
    renderer_a = "Vulpine Preset Renderer A"
    vendor_b = "Vulpine Preset Vendor B"
    renderer_b = "Vulpine Preset Renderer B"

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(
            executable_path=executable_path,
            headless=True,
            firefox_user_prefs={
                "webgl.force-enabled": True,
            },
        )
        try:
            first_a = _read_new_context(browser, vendor_a, renderer_a)
            first_b = _read_new_context(browser, vendor_b, renderer_b)
            second_a = _read_new_context(browser, vendor_a, renderer_a)
        finally:
            browser.close()

    assert first_a["webgl"] == {"vendor": vendor_a, "renderer": renderer_a}
    assert first_b["webgl"] == {"vendor": vendor_b, "renderer": renderer_b}
    assert second_a["webgl"] == {"vendor": vendor_a, "renderer": renderer_a}
    assert first_a["webgl"] != first_b["webgl"]


def main():
    test_context_webgl_vendor_renderer_are_isolated_and_reusable()
    test_context_webgl_overrides_launch_config_webgl()
    test_new_context_applies_preset_webgl_vendor_renderer()
    print("live per-context WebGL checks passed")


if __name__ == "__main__":
    main()
