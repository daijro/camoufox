"""
Tests for camoufox.server.

Regression cover for #656: `python -m camoufox server` broke on Playwright
1.60, which bundled away the private `lib/browserServerImpl.js` that
launchServer.js reached into. The two tests below pin the invariants the fix
relies on, so the next time Playwright reshuffles its internals this fails in
CI rather than in a user's terminal.

These need Playwright's driver (a dependency) but never download or launch a
browser, so they stay fast enough to run anywhere.

Run with:
    cd pythonlib && python -m pytest tests/test_server.py -v
"""

import base64
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import orjson
import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import server  # noqa: E402
from camoufox.server import get_nodejs  # noqa: E402

# Anything on the driver's private lib/ path is fair game for Playwright to
# move between releases; only the package entrypoint is a supported contract.
MODULE_ERRORS = ("Cannot find module", "MODULE_NOT_FOUND")


def _driver_package() -> Path:
    return Path(get_nodejs()).parent / "package"


def _read_until(process, expected: str, timeout: float = 5) -> str:
    lines = queue.Queue()

    def read_stdout():
        for line in process.stdout:
            lines.put(line)

    threading.Thread(target=read_stdout, daemon=True).start()
    output = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=deadline - time.monotonic())
        except queue.Empty:
            break
        output.append(line)
        if expected in line:
            return "".join(output)
    raise AssertionError(f"Did not receive {expected!r}; stdout was {''.join(output)!r}")


def test_driver_entrypoint_exposes_launch_server():
    # launchServer.js calls playwright.firefox.launchServer() through the
    # driver's entrypoint. The driver is a bundled copy of playwright-core, so
    # this is public API -- but assert it rather than assume it, since the whole
    # bug was an assumption about driver layout going stale.
    nodejs = get_nodejs()
    result = subprocess.run(
        [
            nodejs,
            "-e",
            "const pw = require(process.argv[1]);"
            "console.log(typeof pw.firefox.launchServer)",
            str(_driver_package() / "index.js"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "function", result.stdout


def test_launch_script_resolves_driver_against_installed_playwright():
    # The #656 symptom exactly: launchServer.js died at require() time with
    # MODULE_NOT_FOUND before it ever read its config. Drive the real script
    # with a config pointing at a binary that does not exist -- reaching a
    # browser-launch failure proves require() and config parsing both worked.
    nodejs = get_nodejs()
    package = _driver_package()
    result = subprocess.run(
        [nodejs, str(server.LAUNCH_SCRIPT), str(package)],
        input=base64.b64encode(
            orjson.dumps({"executablePath": "/nonexistent/camoufox-bin"})
        ).decode(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    for error in MODULE_ERRORS:
        assert error not in combined, f"driver failed to resolve:\n{combined}"
    assert "Launching server..." in combined, combined
    assert "executable doesn't exist" in combined, combined


def test_launch_script_closes_server_gracefully(tmp_path):
    driver = tmp_path / "driver"
    driver.mkdir()
    close_marker = tmp_path / "closed"
    (driver / "index.js").write_text(
        "const fs = require('fs');\n"
        "module.exports = { firefox: { launchServer: async () => ({\n"
        "  wsEndpoint: () => 'ws://test-server',\n"
        "  close: async () => fs.writeFileSync(process.env.CLOSE_MARKER, 'closed')\n"
        "}) } };\n"
    )
    env = os.environ.copy()
    env["CLOSE_MARKER"] = str(close_marker)
    process = subprocess.Popen(
        [get_nodejs(), str(server.LAUNCH_SCRIPT), str(driver)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    try:
        config = base64.b64encode(orjson.dumps({})).decode()
        midpoint = len(config) // 2
        process.stdin.write(config[:midpoint])
        process.stdin.flush()
        process.stdin.write(config[midpoint:] + "\nignored-after-first-frame\n")
        process.stdin.flush()

        output = _read_until(process, "ws://test-server")
        assert "Launching server..." in output
        assert process.poll() is None
        assert not close_marker.exists()

        process.stdin.close()
        assert process.wait(timeout=5) == 0
        assert close_marker.read_text() == "closed"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if not process.stdin.closed:
            process.stdin.close()


@pytest.mark.parametrize(
    ("destroy_argument", "expected_returncode"),
    [("", 0), ("new Error('control stream failed')", 1)],
)
def test_launch_script_closes_server_on_stdin_close_or_error(
    tmp_path, destroy_argument, expected_returncode
):
    driver = tmp_path / "driver"
    driver.mkdir()
    close_marker = tmp_path / "closed"
    (driver / "index.js").write_text(
        "const fs = require('fs');\n"
        "module.exports = { firefox: { launchServer: async () => {\n"
        f"  setTimeout(() => process.stdin.destroy({destroy_argument}), 25);\n"
        "  return {\n"
        "    wsEndpoint: () => 'ws://test-server',\n"
        "    close: async () => fs.writeFileSync(process.env.CLOSE_MARKER, 'closed')\n"
        "  };\n"
        "} } };\n"
    )
    env = os.environ.copy()
    env["CLOSE_MARKER"] = str(close_marker)
    process = subprocess.Popen(
        [get_nodejs(), str(server.LAUNCH_SCRIPT), str(driver)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    try:
        config = base64.b64encode(orjson.dumps({})).decode()
        process.stdin.write(config + "\n")
        process.stdin.flush()
        _read_until(process, "ws://test-server")

        assert process.wait(timeout=5) == expected_returncode
        assert close_marker.read_text() == "closed"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if not process.stdin.closed:
            process.stdin.close()


@pytest.mark.parametrize("interrupt_at", ["write", "flush"])
def test_launch_server_reaps_child_when_sending_config_is_interrupted(
    monkeypatch, interrupt_at
):
    class InterruptingStdin:
        def __init__(self):
            self.closed = False

        def write(self, data):
            if interrupt_at == "write":
                raise KeyboardInterrupt
            return len(data)

        def flush(self):
            if interrupt_at == "flush":
                raise KeyboardInterrupt

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self):
            self.stdin = InterruptingStdin()
            self.returncode = None
            self.wait_timeouts = []
            self.terminated = False
            self.killed = False

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_timeouts.append(timeout)
            self.returncode = 0
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    process = FakeProcess()
    monkeypatch.setattr(server, "get_nodejs", lambda: "/node")
    monkeypatch.setattr(server, "launch_options", lambda **kwargs: {})
    monkeypatch.setattr(server.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(KeyboardInterrupt):
        server.launch_server()

    assert process.stdin.closed
    assert process.wait_timeouts == [15]
    assert not process.terminated
    assert not process.killed


def test_launch_server_surfaces_child_exit_instead_of_pipe_error(monkeypatch, tmp_path):
    # The traceback in #656 was masked twice over: node died, then writing the
    # config to its dead stdin raised BrokenPipeError (EINVAL on Windows),
    # burying the real cause. launch_server() must report the child's exit.
    script = tmp_path / "dies_immediately.js"
    script.write_text("process.exit(3);\n")

    # Oversized so the write cannot fit in the pipe buffer and must hit the
    # closed pipe -- otherwise a small config lands in the buffer and the
    # regression stays invisible.
    monkeypatch.setattr(
        server, "launch_options", lambda **kwargs: {"pad": "x" * 500_000}
    )
    monkeypatch.setattr(server, "LAUNCH_SCRIPT", script)

    with pytest.raises(RuntimeError) as excinfo:
        server.launch_server()

    assert "3" in str(excinfo.value), str(excinfo.value)
