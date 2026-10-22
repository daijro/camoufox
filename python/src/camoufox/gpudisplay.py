"""headless='virtual-gpu': a headless Xorg server pinned to one GPU.

Xvfb has no GPU path, so a browser on it renders WebGL and canvas with Mesa's
software rasterizer. This display is a real Xorg server bound to one card by
its PCI address, drawing a virtual screen with no monitor attached, so the
browser renders on that card. The card is always named, never guessed: the
identity claims the GPU that renders, and two cards render differently.
"""

import os
import re
import signal
import socket
import subprocess  # nosec
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any, Dict, List, Optional, Union

from ._warnings import LeakWarning
from .exceptions import (
    AmbiguousGpuSelection,
    CannotExecuteXorg,
    CannotFindXorg,
    GpuNotFound,
    GpuSoftwareFallback,
    GpuVtTakeover,
    NoGpuFound,
)
from .virtdisplay import VirtualDisplay

# Names the card when the `gpu` launch option is not given.
GPU_ENV_VAR = 'CAMOUFOX_GPU'

# How long the browser has to render on the GPU after the probe page starts
# drawing. A card busy with other work took 5-10s in Holo's measurements.
GPU_WAIT_S = 30.0
GPU_WAIT_ENV_VAR = 'CAMOUFOX_GPU_WAIT_S'

# The root window is not observable (screen.* is spoofed per context), but the
# GPU compositor needs a real surface, so it is not 1x1 like Xvfb's.
GPU_SCREEN = '1920x1080x24'

# Where Xorg looks up a relative -config when the setuid wrapper elevates it.
SYSTEM_CONFIG_DIR = Path('/etc/X11')

# Without root, Xorg.wrap must let any user start Xorg (a launch from ssh,
# systemd or a container is not a console login) and keep it root, which a
# server with no VT of its own needs to open the card. Stock Debian and Ubuntu
# ship allowed_users=console and needs_root_rights=auto.
XWRAPPER_CONFIG = Path('/etc/X11/Xwrapper.config')
XWRAPPER_SETTINGS = {'allowed_users': 'anybody', 'needs_root_rights': 'yes'}
XORG_WRAPPERS = (Path('/usr/lib/xorg/Xorg.wrap'), Path('/usr/libexec/Xorg.wrap'))

# -terminate: the server exits this many seconds after its last client leaves.
# -sharevts: never take a VT of its own, which blanks a live desktop.
SERVER_FLAGS = ('-terminate', '2', '-nolisten', 'tcp', '-sharevts', '-novtswitch')

# Firefox's GPU paths, on by default for this display only; the caller's prefs
# win. webgl.force-enabled is set by every launch already. Forcing the
# accelerated canvas made 2D canvas match Windows Firefox on the same card.
GPU_PREFS: Dict[str, Any] = {
    'gfx.webrender.all': True,
    'layers.acceleration.force-enabled': True,
    'gfx.x11-egl.enabled': True,
    'gfx.canvas.accelerated': True,
    'gfx.canvas.accelerated.force-enabled': True,
}

# Draws one WebGL frame per animation frame: Firefox opens the GPU only when
# something renders.
PROBE_PAGE = (
    "data:text/html,<canvas id=c width=32 height=32></canvas><script>"
    "const gl=c.getContext('webgl2')||c.getContext('webgl');"
    "function f(){if(gl){gl.clear(gl.COLOR_BUFFER_BIT);gl.flush();}requestAnimationFrame(f);}f();"
    "</script>"
)

ACTIVE_VT = Path('/sys/class/tty/tty0/active')
# A crash right after startup (a driver fault under VRAM pressure) and a VT
# switch both land just after the display is reported.
SETTLE_S = 1.0

# An X11 connection setup request: little-endian, protocol 11.0, no auth.
X11_SETUP = bytes([0x6C, 0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 0])

VENDORS = {'0x10de': 'NVIDIA', '0x1002': 'AMD', '0x8086': 'Intel'}

_PCI_ADDRESS = re.compile(r'^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$')


@dataclass(frozen=True)
class GpuDevice:
    """A GPU with a DRM render node, as sysfs describes it."""

    pci_address: str
    render_node: str
    card_node: Optional[str]
    vendor_id: str
    device_id: str
    kernel_driver: str
    # /dev/nvidia<minor> for the NVIDIA driver, which renders through it.
    nvidia_node: Optional[str] = None

    @property
    def drm_nodes(self) -> List[str]:
        """The card's render node and its primary node. Firefox's GPU work is
        accounted to whichever it was handed: a second launch from one process
        on an RX 7900 XTX drew through /dev/dri/card0, not renderD128."""
        return [node for node in (self.render_node, self.card_node) if node]

    @property
    def vendor(self) -> str:
        return VENDORS.get(self.vendor_id, self.vendor_id)

    @property
    def bus_id(self) -> str:
        """Xorg's BusID: decimal bus:device:function, without the domain."""
        _, bus, dev_fn = self.pci_address.split(':')
        dev, fn = dev_fn.split('.')
        return f'PCI:{int(bus, 16)}:{int(dev, 16)}:{int(fn, 16)}'

    @property
    def xorg_driver(self) -> str:
        # modesetting drives any KMS device with glamor; NVIDIA needs its own.
        return 'nvidia' if self.kernel_driver == 'nvidia' else 'modesetting'

    def __str__(self) -> str:
        return (
            f'{self.pci_address} {self.vendor} [{self.vendor_id}:{self.device_id}] '
            f'driver={self.kernel_driver} {self.render_node}'
        )


def drew_on_gpu(fdinfo: str) -> bool:
    """Whether a DRM file's usage stats (its fdinfo) show work on a GPU engine.

    Drivers report busy time (drm-engine-<engine>: <n> ns; amdgpu, i915) or busy
    cycles (drm-cycles-<engine>: <n>; xe reports only these). drm-total-cycles
    counts the GPU's clock whether this client used it or not, so it is not work.
    """
    busy = re.findall(r'^drm-(?:engine-[\w-]+:\s*(\d+) ns|cycles-[\w-]+:\s*(\d+))$', fdinfo, re.M)
    return any(int(ns or cycles) > 0 for ns, cycles in busy)


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def _uevent(path: Path) -> Dict[str, str]:
    return dict(line.split('=', 1) for line in _read(path).splitlines() if '=' in line)


def _nvidia_minor(root: Path, pci_address: str) -> Optional[str]:
    info = _read(root / 'proc/driver/nvidia/gpus' / pci_address / 'information')
    match = re.search(r'^Device Minor:\s*(\d+)', info, re.M)
    return f'/dev/nvidia{match.group(1)}' if match else None


def enumerate_gpus(root: Union[str, Path] = '/') -> List[GpuDevice]:
    """The GPUs with a render node and a PCI address, in PCI address order.

    Ordered by PCI address, not render node number: render nodes are numbered
    in the order the drivers loaded, which can change from one boot to the next.
    """
    root = Path(root)
    drm = root / 'sys/class/drm'
    cards = {}
    for card in drm.glob('card*'):
        if re.fullmatch(r'card\d+', card.name):
            try:
                cards[(card / 'device').resolve(strict=True)] = f'/dev/dri/{card.name}'
            except OSError:
                continue

    gpus = []
    for node in (root / 'dev/dri').glob('renderD*'):
        device = drm / node.name / 'device'
        try:
            real = device.resolve(strict=True)
        except OSError:
            continue
        if not _PCI_ADDRESS.match(real.name):
            continue
        driver = _uevent(device / 'uevent').get('DRIVER', '')
        gpus.append(
            GpuDevice(
                pci_address=real.name,
                render_node=f'/dev/dri/{node.name}',
                card_node=cards.get(real),
                vendor_id=_read(device / 'vendor').lower(),
                device_id=_read(device / 'device').lower(),
                kernel_driver=driver,
                nvidia_node=_nvidia_minor(root, real.name) if driver == 'nvidia' else None,
            )
        )
    return sorted(gpus, key=lambda gpu: gpu.pci_address)


def _matches(index: int, gpu: GpuDevice, selector: str) -> bool:
    if selector.isdigit():
        return int(selector) == index
    ids = f"{gpu.vendor_id}:{gpu.device_id}".replace('0x', '')
    names = {gpu.render_node, os.path.basename(gpu.render_node), gpu.vendor.lower(), ids}
    if gpu.card_node:
        names |= {gpu.card_node, os.path.basename(gpu.card_node)}
    return selector.replace('0x', '') in {name.lower() for name in names} or selector in gpu.pci_address


def _listing(gpus: List[GpuDevice], shown: Optional[List[GpuDevice]] = None) -> str:
    return '\n'.join(f'  [{i}] {gpu}' for i, gpu in enumerate(gpus) if shown is None or gpu in shown)


def select_gpu(selector: Optional[Union[str, int]] = None, gpus: Optional[List[GpuDevice]] = None) -> GpuDevice:
    """The one GPU `selector` (or CAMOUFOX_GPU) names.

    A selector is an index into enumerate_gpus(), a render or card node (name or
    /dev/dri path), a PCI address or part of one, vendor:device ids, or a vendor
    name. Without one, the host must have exactly one GPU.
    """
    if gpus is None:
        gpus = enumerate_gpus()
    if not gpus:
        raise NoGpuFound(
            'virtual-gpu: no GPU render node with a PCI address. Is a GPU present, is its driver '
            'loaded, and are /dev/dri and /sys visible (--device /dev/dri in a container)?'
        )
    if selector is None:
        selector = os.environ.get(GPU_ENV_VAR, '')
    selector = str(selector).strip().lower()
    if not selector:
        if len(gpus) == 1:
            return gpus[0]
        raise AmbiguousGpuSelection(
            f'virtual-gpu: {len(gpus)} GPUs found. Name one with gpu= or {GPU_ENV_VAR}, '
            f'preferably by PCI address:\n{_listing(gpus)}'
        )
    matched = [gpu for i, gpu in enumerate(gpus) if _matches(i, gpu, selector)]
    if not matched:
        raise GpuNotFound(f'virtual-gpu: no GPU matches {selector!r}. Available:\n{_listing(gpus)}')
    if len(matched) > 1:
        raise AmbiguousGpuSelection(
            f'virtual-gpu: {selector!r} matches {len(matched)} GPUs:\n{_listing(gpus, matched)}'
        )
    return matched[0]


def xorg_config(gpu: GpuDevice, screen: str = GPU_SCREEN) -> str:
    """An xorg.conf that drives `gpu` with a virtual screen and no outputs.

    `UseDisplayDevice "None"` keeps the NVIDIA driver off every connector, so it
    needs no DRM master and coexists with a desktop on the same card.
    """
    width, height, depth = screen.split('x')
    offscreen = '\tOption      "UseDisplayDevice" "None"\n' if gpu.xorg_driver == 'nvidia' else ''
    return f'''# Generated by camoufox for headless="virtual-gpu".
# GPU: {gpu.pci_address} {gpu.vendor} [{gpu.vendor_id}:{gpu.device_id}] driver={gpu.kernel_driver}
Section "ServerFlags"
\tOption      "AutoAddDevices" "false"
\tOption      "AutoAddGPU"     "false"
\tOption      "DontVTSwitch"   "true"
\tOption      "AllowMouseOpenFail" "true"
EndSection

Section "Device"
\tIdentifier  "camoufox-gpu"
\tDriver      "{gpu.xorg_driver}"
\tBusID       "{gpu.bus_id}"
{offscreen}\tOption      "AllowEmptyInitialConfiguration" "true"
EndSection

Section "Monitor"
\tIdentifier  "camoufox-monitor"
\tHorizSync   5.0 - 1000.0
\tVertRefresh 5.0 - 200.0
EndSection

Section "Screen"
\tIdentifier  "camoufox-screen"
\tDevice      "camoufox-gpu"
\tMonitor     "camoufox-monitor"
\tDefaultDepth {depth}
\tSubSection "Display"
\t\tDepth   {depth}
\t\tVirtual {width} {height}
\tEndSubSection
EndSection

Section "ServerLayout"
\tIdentifier  "camoufox-layout"
\tScreen      "camoufox-screen"
EndSection
'''


def config_name(gpu: GpuDevice) -> str:
    """The config's file name in /etc/X11, keyed by PCI address."""
    return f"camoufox-gpu-{re.sub(r'[:.]', '_', gpu.pci_address)}.conf"


def setup_command(gpu: GpuDevice) -> str:
    """The one command that sets this machine up for `gpu`."""
    sudo = '' if os.geteuid() == 0 else 'sudo '
    return f'python -m camoufox gpu-setup {gpu.pci_address} | {sudo}sh'


def setup_script(gpu: GpuDevice) -> str:
    """A root shell script that sets this machine up for headless="virtual-gpu"
    on `gpu`: Xorg and its setuid wrapper, the wrapper's settings, and the
    card's config. Safe to run again."""
    config = SYSTEM_CONFIG_DIR / config_name(gpu)
    xwrapper = XWRAPPER_CONFIG
    settings = ''.join(f'{key}={value}\\n' for key, value in XWRAPPER_SETTINGS.items())
    deletes = ' '.join(
        f"-e '/^[[:space:]]*{key}[[:space:]]*=/d'" for key in XWRAPPER_SETTINGS
    )
    nvidia = (
        '\n'
        'if ! find /usr/lib /usr/lib64 -name nvidia_drv.so 2>/dev/null | grep -q .; then\n'
        "\techo 'camoufox gpu-setup: no nvidia_drv.so found. Install the NVIDIA driver'\\''s Xorg "
        "module, matching the kernel driver (on Ubuntu, xserver-xorg-video-nvidia-<version>).' >&2\n"
        'fi\n'
        if gpu.xorg_driver == 'nvidia'
        else ''
    )
    return f'''#!/bin/sh
# Generated by camoufox gpu-setup for headless="virtual-gpu".
# GPU: {gpu}
# Run once as root: {setup_command(gpu)}
set -e
if [ "$(id -u)" -ne 0 ]; then
\techo 'camoufox gpu-setup: run this as root (pipe it to sudo sh).' >&2
\texit 1
fi

# 1. The Xorg server and its setuid wrapper, Xorg.wrap.
if command -v apt-get >/dev/null 2>&1; then
\tdpkg -s xserver-xorg-core xserver-xorg-legacy >/dev/null 2>&1 \\
\t\t|| DEBIAN_FRONTEND=noninteractive apt-get install -y xserver-xorg-core xserver-xorg-legacy
elif ! command -v Xorg >/dev/null 2>&1; then
\techo 'camoufox gpu-setup: install the Xorg server and its setuid wrapper (Xorg.wrap), then run this again.' >&2
\texit 1
fi
{nvidia}
# 2. Let Xorg.wrap start Xorg as root for any user. A launch from ssh, systemd
#    or a container is not a console login. Any local user can then start a
#    root X server.
touch {xwrapper}
sed -i {deletes} {xwrapper}
printf '{settings}' >> {xwrapper}

# 3. The card's config, bound by PCI address.
cat > {config} <<'CAMOUFOX_XORG_CONF'
{xorg_config(gpu)}CAMOUFOX_XORG_CONF

echo 'headless="virtual-gpu" is set up for {gpu.pci_address}.'
'''


def setup_problems() -> List[str]:
    """What keeps Xorg.wrap from starting Xorg for this user, if anything."""
    problems = []
    if not any(path.exists() for path in XORG_WRAPPERS):
        problems.append(f"no setuid Xorg.wrap ({' or '.join(map(str, XORG_WRAPPERS))})")
    settings = {}
    for line in _read(XWRAPPER_CONFIG).splitlines():
        key, _, value = line.partition('=')
        settings[key.strip()] = value.strip()
    for key, wanted in XWRAPPER_SETTINGS.items():
        have = settings.get(key) or 'unset'
        if have != wanted:
            problems.append(f'{XWRAPPER_CONFIG} has {key}={have}, needs {key}={wanted}')
    return problems


def _session_on_vt(vt: str) -> Optional[str]:
    """The logind session on VT `vt`, which its user may activate without root."""
    try:
        sessions = subprocess.run(  # nosec
            ['loginctl', 'list-sessions', '--no-legend'], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in sessions.splitlines():
        session = line.split()[0]
        number = subprocess.run(  # nosec
            ['loginctl', 'show-session', session, '-p', 'VTNr', '--value'],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if number == vt:
            return session
    return None


class GpuDisplay(VirtualDisplay):
    """A headless Xorg server on one GPU, for headless='virtual-gpu'.

    As root, Xorg takes a temporary config and log. Otherwise it runs through
    the setuid Xorg.wrap, which accepts only a config name relative to
    /etc/X11 and no -logfile, so the config is installed there once.
    """

    _name = 'Xorg'

    def _error(self, message: str) -> CannotExecuteXorg:  # type: ignore[override]
        """A failed start, with what the machine is missing when that is why."""
        if os.geteuid() != 0:
            problems = setup_problems()
            if problems:
                message += (
                    '\nheadless="virtual-gpu" without root needs Xorg.wrap to start Xorg as root:\n'
                    + ''.join(f'  - {problem}\n' for problem in problems)
                    + f'Set this machine up with:\n  {setup_command(self.gpu)}'
                )
        return CannotExecuteXorg(message)

    def __init__(self, gpu: GpuDevice, debug: bool = False, require_gpu: bool = True) -> None:
        super().__init__(debug=debug, screen=GPU_SCREEN)
        self.gpu = gpu
        self.require_gpu = require_gpu
        self._client: Optional[socket.socket] = None
        self._temp_files: List[str] = []
        self._vt: Optional[str] = None

    @property
    def xorg_path(self) -> str:
        path = which('Xorg')
        if not path:
            raise CannotFindXorg(
                'headless="virtual-gpu" needs the Xorg server. Set this machine up with:\n'
                f'  {setup_command(self.gpu)}'
            )
        return path

    def _command(self) -> List[str]:
        if os.geteuid() == 0:
            fd, config = tempfile.mkstemp(prefix='camoufox-xorg-', suffix='.conf')
            with os.fdopen(fd, 'w') as f:
                f.write(xorg_config(self.gpu, self.screen))
            log = config[: -len('.conf')] + '.log'
            self._temp_files = [config, log]
            files = ['-config', config, '-logfile', log]
        else:
            name = config_name(self.gpu)
            if not (SYSTEM_CONFIG_DIR / name).is_file():
                raise CannotExecuteXorg(
                    f'headless="virtual-gpu" without root needs {SYSTEM_CONFIG_DIR / name}. '
                    f'Set this machine up with:\n  {setup_command(self.gpu)}'
                )
            files = ['-config', name]
        return [self.xorg_path, *files, *SERVER_FLAGS]

    def _wrapper(self) -> List[str]:
        # No parent-death signal: the setuid Xorg.wrap drops it on exec. The
        # held client and -terminate end the server instead (_ready).
        return []

    def _server_env(self) -> Optional[Dict[str, str]]:
        return None

    def _log(self) -> str:
        return self._temp_files[1] if self._temp_files else f'/var/log/Xorg.{self._display}.log'

    def get(self) -> str:
        self._vt = _read(ACTIVE_VT) or None
        return super().get()

    def _starting(self) -> None:
        if self._vt and _read(ACTIVE_VT) != self._vt:
            self._vt_taken()

    def _ready(self) -> None:
        deadline = time.monotonic() + SETTLE_S
        while time.monotonic() < deadline:
            self._starting()
            if self.proc is not None and self.proc.poll() is not None:
                error = self._error(
                    f'Xorg exited ({self.proc.returncode}) right after starting. See {self._log()}.'
                )
                self.kill()
                raise error
            time.sleep(0.1)
        # The server exits at its last client's disconnect (-terminate), and a
        # server no client ever reached never does. Holding one client from here
        # on means it always has a last client: this one, closed by kill() or by
        # the kernel when this process dies. An unprivileged launcher may not be
        # able to signal a root Xorg, so this is the teardown that always works.
        self._client = socket.socket(socket.AF_UNIX)
        try:
            self._client.connect(f'/tmp/.X11-unix/X{self._display}')
            self._client.sendall(X11_SETUP)
        except OSError as e:
            self.kill()
            raise self._error(f'Could not connect to the Xorg display it reported: {e}') from e

    def _vt_taken(self) -> None:
        vt = self._vt or ''
        number = vt.removeprefix('tty')
        session = _session_on_vt(number)
        if session:
            subprocess.run(['loginctl', 'activate', session], capture_output=True)  # nosec
        if _read(ACTIVE_VT) != vt:
            subprocess.run(['chvt', number], capture_output=True)  # nosec
        restored = _read(ACTIVE_VT) == vt
        self.kill()
        raise GpuVtTakeover(
            f'Xorg on {self.gpu} switched the active VT away from {vt}. '
            + ('It was switched back.' if restored else f'Switch back with `sudo chvt {number}`.')
        )

    def _display_processes(self) -> List[int]:
        """Every process started with DISPLAY set to this display, except Xorg and us."""
        needle = f'\0DISPLAY=:{self._display}\0'.encode()
        skip = {os.getpid(), self.proc.pid if self.proc else None}
        pids = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit() or int(entry.name) in skip:
                continue
            try:
                if needle in b'\0' + (entry / 'environ').read_bytes():
                    pids.append(int(entry.name))
            except OSError:
                continue
        return pids

    def uses_gpu(self) -> bool:
        """Whether a process on this display renders on the GPU.

        Firefox opens the card's DRM nodes for DMABuf even when it renders in
        software, so an open render node proves nothing. Rendering is the NVIDIA
        driver's /dev/nvidia<minor> held open, or work the kernel accounted to a
        GPU engine on one of the card's DRM nodes.
        """
        nodes = self.gpu.drm_nodes
        for pid in self._display_processes():
            try:
                fds = list(Path(f'/proc/{pid}/fd').iterdir())
            except OSError:
                continue
            for fd in fds:
                try:
                    target = os.readlink(fd)
                    if target == self.gpu.nvidia_node or (
                        target in nodes
                        and drew_on_gpu(Path(f'/proc/{pid}/fdinfo/{fd.name}').read_text())
                    ):
                        return True
                except OSError:
                    continue
        return False

    def wait_for_gpu(self) -> bool:
        deadline = time.monotonic() + float(os.environ.get(GPU_WAIT_ENV_VAR) or GPU_WAIT_S)
        while time.monotonic() < deadline:
            if self.uses_gpu():
                return True
            time.sleep(0.25)
        return False

    def check_gpu(self, active: bool) -> None:
        """Raise, or warn with require_gpu=False, when the browser did not render on the GPU."""
        if active:
            return
        if not self.require_gpu:
            LeakWarning.warn('gpu_software_rendering')
            return
        raise GpuSoftwareFallback(
            f'The browser on :{self._display} never rendered on {self.gpu}, so it renders in software. '
            f'Firefox may have blocklisted the driver or failed to create a GPU context. '
            f'See {self._log()}.'
        )

    def kill(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        if self._display is not None:
            # The browser's helpers (dbus, at-spi) are not in its process group.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                for pid in self._display_processes():
                    try:
                        os.kill(pid, sig)
                    except OSError:
                        pass
                deadline = time.monotonic() + 1.5
                while self._display_processes() and time.monotonic() < deadline:
                    time.sleep(0.05)
        # SIGTERM lets Xorg remove its root-owned socket, which this process
        # cannot; base kill() SIGKILLs only a server still running after that.
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        super().kill()
        for path in self._temp_files:
            try:
                os.remove(path)
            except OSError:
                pass
        self._temp_files = []
        self._display = None


def prove_gpu(target: Any, display: GpuDisplay) -> None:
    """Draw in a page of `target` and check the browser rendered on the GPU."""
    page = target.new_page()
    try:
        page.goto(PROBE_PAGE)
        active = display.wait_for_gpu()
    finally:
        page.close()
    display.check_gpu(active)


async def async_prove_gpu(target: Any, display: GpuDisplay) -> None:
    import asyncio

    page = await target.new_page()
    try:
        await page.goto(PROBE_PAGE)
        active = await asyncio.get_running_loop().run_in_executor(None, display.wait_for_gpu)
    finally:
        await page.close()
    display.check_gpu(active)
