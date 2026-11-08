"""
Shared helpers for patch verification tests.
"""

import ipaddress
import socket
import struct
import threading
from contextlib import asynccontextmanager
from typing import Optional


@asynccontextmanager
async def launch_camoufox(os: str = "macos", headless: bool = True):
    """
    Launch Camoufox with a random preset.

    Yields (page, fingerprint_config) — the config dict lets tests check
    what values were sent to the browser.
    """
    from camoufox.async_api import AsyncCamoufox
    from camoufox.fingerprints import generate_context_fingerprint, get_random_preset

    fp = generate_context_fingerprint(preset=get_random_preset(os=os))
    async with AsyncCamoufox(
        fingerprint_preset=fp["preset"],
        headless=headless,
        os=os,
        executable_path=str(resolve_binary()),
    ) as browser:
        context = await browser.new_context(**fp["context_options"])
        await context.add_init_script(fp["init_script"])
        page = await context.new_page()
        await page.goto("about:blank")
        yield page, fp["config"]


# --- chrome-context inspection (Marionette) on a hidden display -----------------
#
# Some guards assert browser-UI state a page cannot read (a URL-bar label, a chrome
# overlay, the graphics decision log). They drive Marionette's chrome context.
# Marionette itself shows the remote-control cue, so these always run on a PRIVATE
# Xvfb display -- never on a real screen.

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List


def resolve_binary() -> Path:
    """The camoufox binary under test: `--binary <path>`, else the runner's
    CAMOUFOX_EXECUTABLE_PATH, else CAMOUFOX_BINARY, else the newest in-tree Linux
    build (never another target's objdir, which cannot execute here)."""
    if "--binary" in sys.argv:
        return Path(sys.argv[sys.argv.index("--binary") + 1]).resolve()
    for var in ("CAMOUFOX_EXECUTABLE_PATH", "CAMOUFOX_BINARY"):
        if os.environ.get(var):
            return Path(os.environ[var]).resolve()
    root = Path(__file__).resolve().parents[3]
    matches = sorted(root.glob("camoufox-*/obj-*-linux-gnu/dist/bin/camoufox-bin"))
    if not matches:
        raise SystemExit("no camoufox binary: set CAMOUFOX_EXECUTABLE_PATH")
    return matches[-1]


def launch_kwargs(**overrides: Any) -> Dict[str, Any]:
    """Camoufox() kwargs for a guard: headless, on the binary under test."""
    return {"headless": True, "executable_path": str(resolve_binary()), **overrides}


def _forbid_installed_release() -> None:
    """A guard tests the binary under test, so anything that resolves the
    installed release instead fails here. Otherwise it passes against the
    release cached on a dev box and, on a runner with none, downloads one
    through the GitHub API, where an anonymous rate limit fails it (403)."""
    try:
        from camoufox import pkgman
    except ImportError:
        return

    def camoufox_path(*_args: Any, **_kwargs: Any) -> Path:
        raise RuntimeError(
            "a guard resolved the installed Camoufox release, not the binary "
            "under test: pass executable_path (launch_kwargs) or path=")

    pkgman.camoufox_path = camoufox_path


_forbid_installed_release()


@contextlib.contextmanager
def hidden_display(screen: str = "1400x900") -> Iterator[str]:
    """A private Xvfb display for the duration of the block.

    The process environment points at it too. On a Wayland desktop an inherited
    WAYLAND_DISPLAY makes GTK skip the X display, so the browser never opens it.
    """
    if not shutil.which("Xvfb"):
        raise SystemExit("Xvfb is required for this guard")
    # Xvfb picks a free display itself and names it on the pipe once it serves it. Picking the first
    # number without a socket and starting Xvfb there raced other jobs starting servers: the guard's
    # Xvfb lost the number and died, and the browser opened the winner's display (a 3840-wide screen
    # in a 3456x2160 guard).
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", f"{screen}x24", "-nolisten", "tcp"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(write_fd,))
    os.close(write_fd)
    with os.fdopen(read_fd) as pipe:
        number = pipe.readline().strip()
    if not number.isdigit() or proc.poll() is not None:
        proc.kill()
        raise SystemExit(f"Xvfb did not start a {screen} display")
    display = f":{number}"
    saved = dict(os.environ)
    os.environ.update(DISPLAY=display, MOZ_ENABLE_WAYLAND="0", GDK_BACKEND="x11")
    os.environ.pop("WAYLAND_DISPLAY", None)
    try:
        yield display
    finally:
        os.environ.clear()
        os.environ.update(saved)
        proc.terminate()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Marionette:
    """Minimal Marionette client: length-prefixed JSON over TCP, chrome context."""

    def __init__(self, port: int, timeout: float = 60):
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)
        self.sock.settimeout(timeout)
        self._id = 0
        self._recv()  # server hello
        self.call("WebDriver:NewSession", {"capabilities": {}})
        self.call("Marionette:SetContext", {"value": "chrome"})

    def _recv(self):
        def recv(n):
            chunk = self.sock.recv(n)
            if not chunk:  # the browser is gone; recv would return b"" forever
                raise ConnectionError("Marionette closed the connection")
            return chunk

        buf = b""
        while b":" not in buf:
            buf += recv(1)
        size, rest = buf.split(b":", 1)
        while len(rest) < int(size):
            rest += recv(int(size) - len(rest))
        return json.loads(rest)

    def call(self, command: str, params: dict):
        self._id += 1
        data = json.dumps([0, self._id, command, params]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            msg = self._recv()
            if isinstance(msg, list) and msg[1] == self._id:
                if msg[2]:
                    raise RuntimeError(f"{command}: {msg[2]}")
                return msg[3]

    def js(self, script: str):
        """Run chrome-context JS (in the browser window) and return its JSON value."""
        return self.call("WebDriver:ExecuteScript", {"script": script, "args": []}).get("value")

    def close(self):
        with contextlib.suppress(Exception):
            self.sock.close()


def marionette_args() -> List[str]:
    return ["--marionette"]


def marionette_env() -> Dict[str, str]:
    """This process's environment plus the chrome context Marionette needs:
    Firefox 159 grants it only through MOZ_REMOTE_ALLOW_SYSTEM_ACCESS, having
    dropped the --remote-allow-system-access flag. A launch given env= gets
    nothing else, so the display hidden_display() set is carried along."""
    return {**os.environ, "MOZ_REMOTE_ALLOW_SYSTEM_ACCESS": "1"}


def own_address() -> str:
    """This host's address on its default route. A UDP connect sends nothing."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("198.51.100.1", 9))
        return probe.getsockname()[0]


STUN_COOKIE = 0x2112A442


def stun_binding_response(request: bytes, ip: str, port: int) -> Optional[bytes]:
    """The answer to an RFC 8489 Binding request, mapping it to ip:port; None if it is not one."""
    if len(request) < 20:
        return None
    kind, _, cookie = struct.unpack("!HHI", request[:8])
    if kind != 0x0001 or cookie != STUN_COOKIE:
        return None
    attr = struct.pack("!HHBBHI", 0x0020, 8, 0, 1, port ^ (STUN_COOKIE >> 16),
                       int(ipaddress.IPv4Address(ip)) ^ STUN_COOKIE)
    return struct.pack("!HHI", 0x0101, len(attr), STUN_COOKIE) + request[8:20] + attr


class AnsweringStun:
    """A STUN server on this host that sees its clients at a public address, as
    one across a NAT does: a real server-reflexive candidate, with no network.
    Not on loopback: ICE pairs a host socket only with a server of its own kind."""

    MAPPED_IP = "198.51.100.20"

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((own_address(), 0))
        self.url = "stun:{}:{}".format(*self.sock.getsockname())
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                data, src = self.sock.recvfrom(2048)
            except OSError:
                return
            response = stun_binding_response(data, self.MAPPED_IP, src[1])
            if response:
                self.sock.sendto(response, src)

    def close(self) -> None:
        self.sock.close()
