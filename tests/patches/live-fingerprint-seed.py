"""
Opt-in live browser readback for persistent fingerprint seeds.

Run directly:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib \
    python3 tests/patches/live-fingerprint-seed.py

Or with pytest:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib \
    python3 -m pytest --confcutdir=tests/patches tests/patches/live-fingerprint-seed.py
"""

import json
import os
from urllib.parse import quote

from camoufox.sync_api import Camoufox, NewContext


HTML = """<!doctype html><meta charset="utf-8"><pre id="out"></pre><script>
function canvasHash() {
  const c = document.createElement('canvas');
  c.width = 240;
  c.height = 80;
  const ctx = c.getContext('2d');
  ctx.textBaseline = 'top';
  ctx.font = '18px Arial';
  ctx.fillStyle = '#f60';
  ctx.fillRect(10, 10, 100, 32);
  ctx.fillStyle = '#069';
  ctx.fillText('Camoufox seed test', 12, 18);
  return c.toDataURL().slice(0, 96);
}
function webgl() {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
  if (!gl) return null;
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return {
    vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
    renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
  };
}
document.getElementById('out').textContent = JSON.stringify({
  ua: navigator.userAgent,
  platform: navigator.platform,
  oscpu: navigator.oscpu,
  hw: navigator.hardwareConcurrency,
  language: navigator.language,
  languages: navigator.languages,
  screen: {
    width: screen.width,
    height: screen.height,
    colorDepth: screen.colorDepth,
    dpr: devicePixelRatio,
  },
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  webgl: webgl(),
  canvas: canvasHash(),
});
</script>"""

URL = "data:text/html;charset=utf-8," + quote(HTML)
RUNTIME_KEYS = (
    "ua",
    "platform",
    "oscpu",
    "hw",
    "language",
    "languages",
    "screen",
    "timezone",
    "webgl",
    "canvas",
)
CONTEXT_VARIANT_KEYS = ("ua", "platform", "oscpu", "hw", "screen")


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


def _read_launch(executable_path, seed):
    with Camoufox(
        executable_path=executable_path,
        headless=True,
        fingerprint_seed=seed,
        ff_version=146,
        i_know_what_im_doing=True,
    ) as browser:
        return _read_page(browser.new_page())


def _read_context(executable_path, seed):
    with Camoufox(
        executable_path=executable_path,
        headless=True,
        fingerprint_seed="stable-parent-browser",
        ff_version=146,
        i_know_what_im_doing=True,
    ) as browser:
        context = NewContext(browser, fingerprint_seed=seed, ff_version="146")
        try:
            return _read_page(context.new_page())
        finally:
            context.close()


def _assert_same_seed_stable(reader, executable_path):
    first = reader(executable_path, "profile-a")
    second = reader(executable_path, "profile-a")
    assert {key: first[key] for key in RUNTIME_KEYS} == {
        key: second[key] for key in RUNTIME_KEYS
    }


def _assert_different_seed_changes_identity(reader, executable_path, keys):
    first = reader(executable_path, "profile-a")
    second = reader(executable_path, "profile-b")
    assert any(first[key] != second[key] for key in keys)


def test_launch_seed_runtime_readback_is_stable():
    executable_path = _required_executable()
    _assert_same_seed_stable(_read_launch, executable_path)
    _assert_different_seed_changes_identity(_read_launch, executable_path, RUNTIME_KEYS)


def test_context_seed_runtime_readback_is_stable_with_seeded_parent():
    executable_path = _required_executable()
    _assert_same_seed_stable(_read_context, executable_path)
    _assert_different_seed_changes_identity(
        _read_context,
        executable_path,
        CONTEXT_VARIANT_KEYS,
    )


def main():
    path = os.environ.get("CAMOUFOX_EXECUTABLE_PATH")
    if not path:
        print("skipped live seed readback checks: CAMOUFOX_EXECUTABLE_PATH is not set")
        return
    test_launch_seed_runtime_readback_is_stable()
    test_context_seed_runtime_readback_is_stable_with_seeded_parent()
    print("live seed readback checks passed")


if __name__ == "__main__":
    main()
