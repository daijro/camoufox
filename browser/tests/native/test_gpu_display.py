"""headless='virtual-gpu' on a real GPU.

Needs the card named by CAMOUFOX_GPU, Xorg with the card's driver and, without
root, the machine set up for it (`python -m camoufox gpu-setup <gpu> | sudo sh`).
CI has no GPU runner, so this is a subset of its own, run on a machine with one:

    CAMOUFOX_GPU=01:00.0 python3 -m ci.run_native --subset gpu --binary path/to/camoufox-bin

The GPU-free half is python/tests/test_gpudisplay.py.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Set

import pytest
from playwright.sync_api import sync_playwright

from camoufox.gpudisplay import ACTIVE_VT, GPU_PREFS, GpuDisplay, select_gpu
from camoufox.sync_api import Camoufox
from camoufox.utils import launch_options, sync_attach_vd

READ_GPU = """() => {
    const gl = document.createElement('canvas').getContext('webgl');
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    return [gl.getParameter(info.UNMASKED_VENDOR_WEBGL), gl.getParameter(info.UNMASKED_RENDERER_WEBGL)];
}"""


# Opt-in, like typescript/tests/gpu-display.test.ts: without a card named, a
# plain `pytest browser/tests/native` skips this file. `ci.run_native --subset
# gpu` refuses to run without one, so a requested GPU run never passes empty.
pytestmark = pytest.mark.skipif(
    not os.environ.get("CAMOUFOX_GPU", "").strip(),
    reason="needs a GPU: set CAMOUFOX_GPU to the card under test, e.g. CAMOUFOX_GPU=01:00.0",
)


@pytest.fixture(scope="module")
def gpu():
    return select_gpu()


@pytest.fixture(autouse=True)
def hidden(monkeypatch):
    """Nothing here may open on the desktop the tests run from."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


@pytest.fixture(autouse=True)
def the_console_stays_put():
    before = ACTIVE_VT.read_text().strip() if ACTIVE_VT.exists() else None
    yield
    if before:
        assert ACTIVE_VT.read_text().strip() == before, "the GPU display switched the active VT"


def xorg_servers() -> Set[int]:
    found = subprocess.run(["pgrep", "-x", "Xorg"], capture_output=True, text=True).stdout
    return {int(pid) for pid in found.split()}


def wait_until_gone(pids: Set[int], timeout: float = 15) -> Set[int]:
    deadline = time.monotonic() + timeout
    while pids & xorg_servers() and time.monotonic() < deadline:
        time.sleep(0.1)
    return pids & xorg_servers()


def test_the_browser_renders_on_the_named_card(binary: Path, gpu):
    display = GpuDisplay(gpu)
    options = launch_options(
        virtual_display=display.get(),
        headless=False,
        os="linux",
        executable_path=str(binary),
        firefox_user_prefs=dict(GPU_PREFS),
        i_know_what_im_doing=True,
    )
    server = display.proc.pid
    with sync_playwright() as playwright:
        # Raises GpuSoftwareFallback unless the browser rendered on the card.
        browser = sync_attach_vd(playwright.firefox.launch(**options), display)
        try:
            assert display.uses_gpu()
            # The identity claims the card that renders, not the desktop's GPU.
            vendor, renderer = browser.new_page().evaluate(READ_GPU)
            assert gpu.vendor.lower() in f"{vendor} {renderer}".lower(), (vendor, renderer)
            for pid in display._display_processes():
                environ = Path(f"/proc/{pid}/environ").read_bytes()
                assert b"LIBGL_ALWAYS_SOFTWARE" not in environ
                assert b"__GLX_VENDOR_LIBRARY_NAME" not in environ
        finally:
            browser.close()
    assert not wait_until_gone({server}), "Xorg outlived the browser"


def test_camoufox_on_the_gpu_leaves_no_server_behind(binary: Path, gpu):
    before = xorg_servers()
    with Camoufox(headless="virtual-gpu", os="linux", executable_path=str(binary)) as browser:
        started = xorg_servers() - before
        assert len(started) == 1
        browser.new_page().goto("about:blank")
    assert not wait_until_gone(started), "Xorg outlived the browser"


def test_the_server_serves_a_browser_on_the_gpu(binary: Path, gpu):
    before = xorg_servers()
    started: Set[int] = set()
    serve = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from camoufox.server import launch_server; "
            "launch_server(headless='virtual-gpu', os='linux', executable_path=sys.argv[1])",
            str(binary),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert serve.stdout is not None
        endpoint = None
        for line in serve.stdout:
            if "ws://" in line:
                endpoint = line[line.index("ws://") :].split()[0]
                break
        assert endpoint, f"launch_server exited {serve.wait()} without an endpoint"
        started = xorg_servers() - before
        assert len(started) == 1
        with sync_playwright() as playwright:
            browser = playwright.firefox.connect(endpoint)
            try:
                vendor, renderer = browser.new_page().evaluate(READ_GPU)
                assert gpu.vendor.lower() in f"{vendor} {renderer}".lower(), (vendor, renderer)
            finally:
                browser.close()
    finally:
        serve.send_signal(signal.SIGINT)
        serve.wait(timeout=60)
    assert not wait_until_gone(started), "Xorg outlived the server"
