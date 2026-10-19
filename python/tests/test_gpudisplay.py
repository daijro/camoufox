"""
Tests for camoufox.gpudisplay (headless='virtual-gpu') that need no GPU:
enumeration and selection on a fake sysfs tree, the generated xorg.conf, the
Xorg argv, the browser's environment and prefs, the identity's GPU probe, the
VT guard, the GPU-use check, and teardown.

The real display is browser/tests/native/test_gpu_display.py.

Mirrors typescript/tests/gpudisplay.test.ts.
"""

import os
import subprocess
import sys
import time
import warnings
from pathlib import Path
from unittest import mock

import pytest

from camoufox import gpudisplay, host_rendering, sync_api, utils
from camoufox._warnings import LeakWarning
from camoufox.exceptions import (
    AmbiguousGpuSelection,
    CannotExecuteXorg,
    CannotFindXorg,
    GpuNotFound,
    GpuSoftwareFallback,
    GpuVtTakeover,
    NoGpuFound,
    VirtualDisplayError,
)
from camoufox.gpudisplay import (
    GPU_PREFS,
    GpuDevice,
    GpuDisplay,
    config_name,
    enumerate_gpus,
    select_gpu,
    xorg_config,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="virtual-gpu is Linux-only")

NVIDIA = GpuDevice(
    pci_address='0000:01:00.0',
    render_node='/dev/dri/renderD129',
    card_node='/dev/dri/card1',
    vendor_id='0x10de',
    device_id='0x2c02',
    kernel_driver='nvidia',
    nvidia_node='/dev/nvidia0',
)
AMD = GpuDevice(
    pci_address='0000:6f:00.0',
    render_node='/dev/dri/renderD128',
    card_node='/dev/dri/card0',
    vendor_id='0x1002',
    device_id='0x744c',
    kernel_driver='amdgpu',
)
AMD_IGPU = GpuDevice(
    pci_address='0000:70:00.0',
    render_node='/dev/dri/renderD130',
    card_node='/dev/dri/card3',
    vendor_id='0x1002',
    device_id='0x13c0',
    kernel_driver='amdgpu',
)
HOST = [NVIDIA, AMD, AMD_IGPU]


def _device(root: Path, pci: str, vendor: str, device: str, driver: str) -> Path:
    path = root / 'sys/devices/pci0000:00' / pci
    path.mkdir(parents=True)
    (path / 'vendor').write_text(vendor + '\n')
    (path / 'device').write_text(device + '\n')
    (path / 'uevent').write_text(f'DRIVER={driver}\nPCI_SLOT_NAME={pci}\n')
    return path


def _node(root: Path, name: str, device: Path) -> None:
    (root / 'dev/dri' / name).touch()
    (root / 'sys/class/drm' / name).mkdir()
    (root / 'sys/class/drm' / name / 'device').symlink_to(device)


@pytest.fixture
def host(tmp_path):
    """This machine's layout: the render nodes are numbered in driver load order,
    so the AMD card is renderD128 though the NVIDIA one has the lower address."""
    (tmp_path / 'dev/dri').mkdir(parents=True)
    (tmp_path / 'sys/class/drm').mkdir(parents=True)
    nvidia = _device(tmp_path, '0000:01:00.0', '0x10de', '0x2c02', 'nvidia')
    amd = _device(tmp_path, '0000:6f:00.0', '0x1002', '0x744C', 'amdgpu')
    igpu = _device(tmp_path, '0000:70:00.0', '0x1002', '0x13c0', 'amdgpu')
    for name, device in (
        ('renderD128', amd), ('card0', amd),
        ('renderD129', nvidia), ('card1', nvidia),
        ('renderD130', igpu), ('card3', igpu),
    ):
        _node(tmp_path, name, device)
    # A connector is a card*-named entry that is not a card.
    (tmp_path / 'sys/class/drm/card1-DP-1').mkdir()
    # A render node with no PCI device cannot be bound by BusID.
    platform = tmp_path / 'sys/devices/platform/vgem'
    platform.mkdir(parents=True)
    _node(tmp_path, 'renderD131', platform)
    info = tmp_path / 'proc/driver/nvidia/gpus/0000:01:00.0'
    info.mkdir(parents=True)
    (info / 'information').write_text('Model: \t NVIDIA GeForce RTX 5080\nDevice Minor: \t 0\n')
    return tmp_path


class TestEnumeration:
    def test_lists_pci_gpus_in_address_order_not_render_node_order(self, host):
        assert enumerate_gpus(host) == HOST

    def test_no_dri_directory_is_no_gpus(self, tmp_path):
        assert enumerate_gpus(tmp_path) == []

    def test_bus_id_is_decimal_without_the_domain(self):
        assert NVIDIA.bus_id == 'PCI:1:0:0'
        assert AMD.bus_id == 'PCI:111:0:0'

    def test_nvidia_gets_its_own_driver_and_everything_else_modesetting(self):
        assert NVIDIA.xorg_driver == 'nvidia'
        assert AMD.xorg_driver == 'modesetting'

    def test_the_nvidia_driver_device_is_found_by_pci_address(self, host):
        assert [gpu.nvidia_node for gpu in enumerate_gpus(host)] == ['/dev/nvidia0', None, None]


class TestSelection:
    @pytest.mark.parametrize(
        'selector',
        [0, '0', 'renderD129', '/dev/dri/renderD129', 'card1', '/dev/dri/card1',
         '01:00.0', '0000:01:00.0', '10de:2c02', '0x10de:0x2c02', 'nvidia', 'NVIDIA'],
    )
    def test_every_kind_of_selector_names_the_nvidia_card(self, selector):
        assert select_gpu(selector, HOST) == NVIDIA

    def test_a_pci_address_names_the_amd_card(self):
        assert select_gpu('6f:00.0', HOST) == AMD

    def test_the_environment_names_the_card_when_the_option_does_not(self, monkeypatch):
        monkeypatch.setenv('CAMOUFOX_GPU', '6f:00.0')
        assert select_gpu(None, HOST) == AMD

    def test_the_option_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv('CAMOUFOX_GPU', '6f:00.0')
        assert select_gpu('01:00.0', HOST) == NVIDIA

    def test_a_lone_gpu_needs_no_selector(self, monkeypatch):
        monkeypatch.delenv('CAMOUFOX_GPU', raising=False)
        assert select_gpu(None, [AMD]) == AMD

    def test_several_gpus_and_no_selector_is_ambiguous(self, monkeypatch):
        monkeypatch.delenv('CAMOUFOX_GPU', raising=False)
        with pytest.raises(AmbiguousGpuSelection, match='3 GPUs'):
            select_gpu(None, HOST)

    def test_a_selector_matching_two_gpus_is_ambiguous(self):
        with pytest.raises(AmbiguousGpuSelection, match=r"(?s)\[1\].*\[2\]"):
            select_gpu('amd', HOST)

    def test_a_selector_matching_nothing_fails(self):
        with pytest.raises(GpuNotFound, match='intel'):
            select_gpu('intel', HOST)

    def test_an_index_past_the_end_fails(self):
        with pytest.raises(GpuNotFound):
            select_gpu(3, HOST)

    def test_no_gpus_fails(self):
        with pytest.raises(NoGpuFound):
            select_gpu('0', [])

    def test_every_failure_is_a_virtual_display_error(self):
        with pytest.raises(VirtualDisplayError):
            select_gpu('intel', HOST)


class TestXorgConfig:
    def test_nvidia(self):
        config = xorg_config(NVIDIA)
        for line in (
            'Option      "AutoAddDevices" "false"',
            'Option      "AutoAddGPU"     "false"',
            'Option      "DontVTSwitch"   "true"',
            'Option      "AllowMouseOpenFail" "true"',
            'Driver      "nvidia"',
            'BusID       "PCI:1:0:0"',
            'Option      "UseDisplayDevice" "None"',
            'Option      "AllowEmptyInitialConfiguration" "true"',
            'HorizSync   5.0 - 1000.0',
            'VertRefresh 5.0 - 200.0',
            'DefaultDepth 24',
            'Virtual 1920 1080',
        ):
            assert line in config, line

    def test_other_cards_use_modesetting_without_the_nvidia_option(self):
        config = xorg_config(AMD)
        assert 'Driver      "modesetting"' in config
        assert 'BusID       "PCI:111:0:0"' in config
        assert 'UseDisplayDevice' not in config

    def test_names_no_render_node_which_can_change_between_boots(self):
        assert 'renderD' not in xorg_config(NVIDIA)

    def test_the_file_is_named_by_pci_address(self):
        assert config_name(NVIDIA) == 'camoufox-gpu-0000_01_00_0.conf'

    def test_the_cli_prints_it(self, monkeypatch, capsys):
        from camoufox.__main__ import cli

        monkeypatch.setattr(gpudisplay, 'enumerate_gpus', lambda: HOST)
        with pytest.raises(SystemExit) as exit:
            cli(['gpu-xorg-config', '01:00.0'])
        assert exit.value.code == 0
        assert capsys.readouterr().out == xorg_config(NVIDIA)


@pytest.fixture
def xwrapper(monkeypatch, tmp_path):
    config = tmp_path / 'Xwrapper.config'
    wrapper = tmp_path / 'Xorg.wrap'
    wrapper.touch()
    monkeypatch.setattr(gpudisplay, 'XWRAPPER_CONFIG', config)
    monkeypatch.setattr(gpudisplay, 'XORG_WRAPPERS', (wrapper,))
    monkeypatch.setattr(os, 'geteuid', lambda: 1000)
    return config


class TestSetup:
    """One command sets a machine up, and every failure it would fix names it."""

    def test_a_stock_wrapper_is_named_with_the_fix(self, xwrapper):
        # What Debian and Ubuntu ship.
        xwrapper.write_text('# Xwrapper.config\nallowed_users=console\n')
        error = GpuDisplay(AMD)._error('Xorg exited (1) right after starting.')
        assert isinstance(error, CannotExecuteXorg)
        message = str(error)
        assert f'{xwrapper} has allowed_users=console, needs allowed_users=anybody' in message
        assert f'{xwrapper} has needs_root_rights=unset, needs needs_root_rights=yes' in message
        assert message.endswith('python -m camoufox gpu-setup 0000:6f:00.0 | sudo sh')

    def test_a_missing_wrapper_is_named(self, xwrapper, monkeypatch, tmp_path):
        xwrapper.write_text('allowed_users=anybody\nneeds_root_rights=yes\n')
        monkeypatch.setattr(gpudisplay, 'XORG_WRAPPERS', (tmp_path / 'none',))
        assert gpudisplay.setup_problems() == [f'no setuid Xorg.wrap ({tmp_path / "none"})']

    def test_a_set_up_machine_adds_nothing_to_the_error(self, xwrapper):
        xwrapper.write_text('allowed_users = anybody\nneeds_root_rights = yes\n')
        assert str(GpuDisplay(AMD)._error('Xorg exited (1).')) == 'Xorg exited (1).'

    def test_as_root_the_wrapper_is_not_involved(self, xwrapper, monkeypatch):
        monkeypatch.setattr(os, 'geteuid', lambda: 0)
        assert str(GpuDisplay(AMD)._error('Xorg exited (1).')) == 'Xorg exited (1).'

    @pytest.mark.parametrize('gpu', [NVIDIA, AMD], ids=['nvidia', 'amd'])
    def test_the_script_is_valid_sh_and_installs_the_card_config(self, gpu):
        script = gpudisplay.setup_script(gpu)
        assert subprocess.run(['sh', '-n'], input=script, text=True).returncode == 0
        config = gpudisplay.SYSTEM_CONFIG_DIR / config_name(gpu)
        assert f"cat > {config} <<'CAMOUFOX_XORG_CONF'\n{xorg_config(gpu)}CAMOUFOX_XORG_CONF\n" in script
        assert "printf 'allowed_users=anybody\\nneeds_root_rights=yes\\n'" in script
        assert ('nvidia_drv.so' in script) is (gpu.xorg_driver == 'nvidia')

    def test_the_cli_prints_it(self, monkeypatch, capsys):
        from camoufox.__main__ import cli

        monkeypatch.setattr(gpudisplay, 'enumerate_gpus', lambda: HOST)
        with pytest.raises(SystemExit) as exit:
            cli(['gpu-setup', '01:00.0'])
        assert exit.value.code == 0
        assert capsys.readouterr().out == gpudisplay.setup_script(NVIDIA)


@pytest.fixture
def xorg(monkeypatch):
    monkeypatch.setattr(gpudisplay, 'which', lambda name: f'/usr/bin/{name}')


class TestCommand:
    def test_without_root_the_installed_config_is_named(self, xorg, monkeypatch, tmp_path):
        monkeypatch.setattr(os, 'geteuid', lambda: 1000)
        monkeypatch.setattr(gpudisplay, 'SYSTEM_CONFIG_DIR', tmp_path)
        (tmp_path / config_name(NVIDIA)).write_text(xorg_config(NVIDIA))

        assert GpuDisplay(NVIDIA)._command() == [
            '/usr/bin/Xorg', '-config', 'camoufox-gpu-0000_01_00_0.conf',
            '-terminate', '2', '-nolisten', 'tcp', '-sharevts', '-novtswitch',
        ]

    def test_without_root_a_missing_config_says_how_to_install_it(self, xorg, monkeypatch, tmp_path):
        monkeypatch.setattr(os, 'geteuid', lambda: 1000)
        monkeypatch.setattr(gpudisplay, 'SYSTEM_CONFIG_DIR', tmp_path)

        with pytest.raises(CannotExecuteXorg) as error:
            GpuDisplay(NVIDIA)._command()
        assert str(error.value).endswith('python -m camoufox gpu-setup 0000:01:00.0 | sudo sh')

    def test_a_missing_xorg_says_how_to_set_the_machine_up(self, monkeypatch):
        monkeypatch.setattr(gpudisplay, 'which', lambda name: None)
        monkeypatch.setattr(os, 'geteuid', lambda: 0)
        with pytest.raises(CannotFindXorg) as error:
            GpuDisplay(AMD).xorg_path
        # As root the script needs no sudo.
        assert str(error.value).endswith('python -m camoufox gpu-setup 0000:6f:00.0 | sh')

    def test_as_root_a_temporary_config_and_log_are_used_and_removed(self, xorg, monkeypatch):
        monkeypatch.setattr(os, 'geteuid', lambda: 0)
        display = GpuDisplay(AMD)
        command = display._command()

        config = command[command.index('-config') + 1]
        log = command[command.index('-logfile') + 1]
        assert os.path.isabs(config)
        assert Path(config).read_text() == xorg_config(AMD)
        assert command[-6:] == ['-terminate', '2', '-nolisten', 'tcp', '-sharevts', '-novtswitch']

        Path(log).touch()
        display.kill()
        assert not os.path.exists(config) and not os.path.exists(log)

    def test_xorg_inherits_the_environment_untouched(self):
        # Xvfb's server is forced onto Mesa's software GLX; this one must not be.
        assert GpuDisplay(NVIDIA)._server_env() is None


class TestLaunch:
    @pytest.fixture
    def started(self, monkeypatch):
        monkeypatch.setattr(utils, 'select_gpu', lambda selector: NVIDIA)
        monkeypatch.setattr(GpuDisplay, 'get', lambda self: ':77')

    def test_points_the_launch_at_the_display_with_the_gpu_prefs(self, started):
        kwargs = {'gpu': '01:00.0', 'firefox_user_prefs': {'gfx.webrender.all': False}}
        display, headless = utils.start_virtual_display('virtual-gpu', False, kwargs)

        assert isinstance(display, GpuDisplay) and display.require_gpu
        assert headless is False
        assert kwargs == {
            'virtual_display': ':77',
            # The caller's prefs win.
            'firefox_user_prefs': {**GPU_PREFS, 'gfx.webrender.all': False},
        }

    def test_require_gpu_false_only_warns(self, started):
        display, _ = utils.start_virtual_display('virtual-gpu', False, {'require_gpu': False})
        assert not display.require_gpu

    @pytest.mark.parametrize('option', ['gpu', 'require_gpu'])
    def test_gpu_options_without_virtual_gpu_are_refused(self, option):
        with pytest.raises(ValueError, match="virtual-gpu"):
            utils.start_virtual_display('virtual', False, {option: '0'})

    def test_the_browser_gets_only_x11_settings_no_gpu_overrides(self, started):
        kwargs = {'gpu': '0'}
        utils.start_virtual_display('virtual-gpu', False, kwargs)
        with mock.patch.object(utils, 'installed_verstr', lambda: '150.0.2'), mock.patch.object(
            utils, 'launch_path', lambda **kw: '/nonexistent/camoufox'
        ):
            env = utils.launch_options(headless=False, i_know_what_im_doing=True, env={}, **kwargs)['env']

        assert env['DISPLAY'] == ':77'
        overrides = [
            key for key in env
            if key.startswith(('MESA_', '__GLX_', 'LIBGL_', 'DRI_PRIME', '__NV_'))
        ]
        assert overrides == []

    def test_the_identity_probes_the_gpu_display_with_its_prefs(self, started):
        """The identity claims the GPU Firefox reports on the GPU display, not
        the one the desktop renders on."""
        probes = []

        def probe(executable_path, headless, env, prefs):
            probes.append((env.get('DISPLAY'), {k: prefs.get(k) for k in GPU_PREFS}))
            return ('NVIDIA Corporation', 'NVIDIA GeForce GTX 980, or similar')

        kwargs = {'gpu': '0'}
        utils.start_virtual_display('virtual-gpu', False, kwargs)
        with mock.patch.object(utils, '_host_os_key', lambda: 'lin'), mock.patch.object(
            utils, 'host_gpu', probe
        ), mock.patch.object(utils, 'installed_verstr', lambda: '150.0.2'), mock.patch.object(
            utils, 'launch_path', lambda **kw: '/nonexistent/camoufox'
        ):
            options = utils.launch_options(os='linux', headless=False, i_know_what_im_doing=True, **kwargs)

        assert probes == [(':77', GPU_PREFS)]
        prefs = options['firefox_user_prefs']
        assert not host_rendering.has_canvas_placeholder(prefs)

    def test_the_probe_reads_with_the_launch_rendering_prefs_only(self, monkeypatch):
        calls = []
        monkeypatch.setattr(host_rendering, '_host_gpu', lambda *args: calls.append(args))
        host_rendering.host_gpu('/x/camoufox', False, {'DISPLAY': ':77'}, {**GPU_PREFS, 'intl.locale.requested': 'en-US'})

        assert calls == [('/x/camoufox', False, (('DISPLAY', ':77'),), tuple(sorted(GPU_PREFS.items())))]

    def test_a_failed_launch_tears_the_display_down(self, monkeypatch):
        display = mock.Mock()
        monkeypatch.setattr(sync_api, 'start_virtual_display', lambda headless, debug, kwargs: (display, False))
        monkeypatch.setattr(sync_api, 'launch_options', mock.Mock(side_effect=RuntimeError('boom')))

        with pytest.raises(RuntimeError, match='boom'):
            sync_api.NewBrowser(mock.Mock(), headless='virtual-gpu')
        display.kill.assert_called_once()


class FakePage:
    def __init__(self):
        self.url = None
        self.closed = False

    def goto(self, url):
        self.url = url

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class TestGpuProof:
    def test_a_browser_that_opened_the_gpu_is_kept(self, monkeypatch):
        display = GpuDisplay(NVIDIA)
        monkeypatch.setattr(display, 'wait_for_gpu', lambda: True)
        browser = FakeBrowser()

        assert utils.sync_attach_vd(browser, display) is browser
        assert browser.page.url == gpudisplay.PROBE_PAGE and browser.page.closed
        assert not browser.closed

    def test_a_browser_in_software_is_closed_and_the_launch_fails(self, monkeypatch):
        display = GpuDisplay(NVIDIA)
        monkeypatch.setattr(display, 'wait_for_gpu', lambda: False)
        kill = mock.Mock()
        monkeypatch.setattr(display, 'kill', kill)
        browser = FakeBrowser()

        with pytest.raises(GpuSoftwareFallback):
            utils.sync_attach_vd(browser, display)
        assert browser.closed
        kill.assert_called()

    def test_require_gpu_false_warns_instead(self, monkeypatch):
        display = GpuDisplay(NVIDIA, require_gpu=False)
        monkeypatch.setattr(display, 'wait_for_gpu', lambda: False)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            utils.sync_attach_vd(FakeBrowser(), display)
        assert any(issubclass(w.category, LeakWarning) and 'software' in str(w.message) for w in caught)

    def test_the_wait_is_overridable(self, monkeypatch):
        display = GpuDisplay(NVIDIA)
        monkeypatch.setattr(display, 'uses_gpu', lambda: False)
        monkeypatch.setenv('CAMOUFOX_GPU_WAIT_S', '0.3')
        start = time.monotonic()
        assert display.wait_for_gpu() is False
        assert time.monotonic() - start < 5


def _holding(path: str, display: str) -> subprocess.Popen:
    """A process on `display` that holds `path` open, as a browser holds the GPU."""
    proc = subprocess.Popen(
        [sys.executable, '-c', f'f = open({path!r}); print(1, flush=True); import time; time.sleep(60)'],
        env={**os.environ, 'DISPLAY': display},
        stdout=subprocess.PIPE,
    )
    proc.stdout.readline()
    return proc


# /proc/<pid>/fdinfo of Firefox's render node on an RX 7900 XTX, trimmed.
AMDGPU_FDINFO = """pos:\t0
flags:\t02100002
drm-driver:\tamdgpu
drm-client-id:\t5873
drm-total-vram:\t159812 KiB
drm-engine-gfx:\t{gfx} ns
drm-engine-compute:\t0 ns
drm-engine-capacity-gfx:\t1
"""

# From the kernel's Xe usage stats documentation.
XE_FDINFO = """pos:\t0
flags:\t0100002
drm-driver:\txe
drm-client-id:\t21
drm-cycles-rcs:\t{rcs}
drm-total-cycles-rcs:\t7655183225
drm-cycles-bcs:\t0
drm-total-cycles-bcs:\t7655183225
drm-engine-capacity-vcs:\t2
"""


class TestGpuUse:
    """Rendering is read from what the kernel accounts to the browser, never
    from the renderer string, which the identity spoofs."""

    def test_engine_time_on_the_render_node_is_rendering(self):
        assert gpudisplay.drew_on_gpu(AMDGPU_FDINFO.format(gfx=39907610))

    def test_xe_busy_cycles_count(self):
        # xe reports cycles only; its total-cycles line grows on an idle client too.
        assert gpudisplay.drew_on_gpu(XE_FDINFO.format(rcs=28257900))
        assert not gpudisplay.drew_on_gpu(XE_FDINFO.format(rcs=0))

    def test_an_idle_render_node_is_not(self):
        # Firefox opens it for DMABuf in software too; the capacity line is not time.
        assert not gpudisplay.drew_on_gpu(AMDGPU_FDINFO.format(gfx=0))
        assert not gpudisplay.drew_on_gpu('pos:\t0\nflags:\t02\n')

    @pytest.fixture
    def card(self, tmp_path):
        for name in ('renderD200', 'nvidia7'):
            (tmp_path / name).touch()
        return GpuDevice(
            '0000:01:00.0', str(tmp_path / 'renderD200'), None, '0x10de', '0x2c02', 'nvidia',
            str(tmp_path / 'nvidia7'),
        )

    @pytest.fixture
    def display(self, card):
        display = GpuDisplay(card)
        display._display = 98765
        return display

    @pytest.mark.parametrize(
        'held, on, rendering',
        [
            ('nvidia_node', ':98765', True),
            ('nvidia_node', ':987650', False),
            # An open render node with no engine time is software rendering.
            ('render_node', ':98765', False),
        ],
    )
    def test_what_a_process_on_the_display_holds(self, card, display, held, on, rendering):
        proc = _holding(getattr(card, held), on)
        try:
            assert display.uses_gpu() is rendering
        finally:
            proc.kill()
            proc.wait()

    @pytest.mark.parametrize('held', ['render_node', 'card_node'])
    def test_engine_work_on_either_drm_node_of_the_card_is_rendering(
        self, tmp_path, monkeypatch, held
    ):
        # On an RX 7900 XTX, a second launch from one process drew through
        # /dev/dri/card0 and left renderD128 idle.
        for name in ('renderD200', 'card9', 'other'):
            (tmp_path / name).touch()
        gpu = GpuDevice(
            '0000:6f:00.0', str(tmp_path / 'renderD200'), str(tmp_path / 'card9'),
            '0x1002', '0x744c', 'amdgpu',
        )
        display = GpuDisplay(gpu)
        display._display = 98765
        monkeypatch.setattr(gpudisplay, 'drew_on_gpu', lambda fdinfo: True)
        for path, rendering in ((getattr(gpu, held), True), (str(tmp_path / 'other'), False)):
            proc = _holding(path, ':98765')
            try:
                assert display.uses_gpu() is rendering
            finally:
                proc.kill()
                proc.wait()

    def test_kill_sweeps_every_process_on_the_display(self, card, display):
        proc = _holding(card.render_node, ':98765')
        try:
            display.kill()
            assert proc.wait(timeout=5) is not None
        finally:
            proc.kill()
            proc.wait()


class TestVtGuard:
    @pytest.fixture
    def vt(self, monkeypatch, tmp_path):
        active = tmp_path / 'active'
        active.write_text('tty2\n')
        monkeypatch.setattr(gpudisplay, 'ACTIVE_VT', active)
        return active

    def test_a_vt_switch_is_undone_and_fails_the_launch(self, vt, monkeypatch):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[:2] == ['loginctl', 'list-sessions']:
                return subprocess.CompletedProcess(command, 0, '3 1000 user seat0 tty2\n', '')
            if command[:2] == ['loginctl', 'show-session']:
                return subprocess.CompletedProcess(command, 0, '2\n', '')
            if command[:2] == ['loginctl', 'activate']:
                vt.write_text('tty2\n')
            return subprocess.CompletedProcess(command, 0, '', '')

        monkeypatch.setattr(gpudisplay.subprocess, 'run', run)
        display = GpuDisplay(NVIDIA)
        kill = mock.Mock()
        monkeypatch.setattr(display, 'kill', kill)
        display._vt = 'tty2'
        vt.write_text('tty7\n')

        with pytest.raises(GpuVtTakeover, match='switched back'):
            display._starting()
        assert ['loginctl', 'activate', '3'] in commands
        kill.assert_called_once()

    def test_an_unchanged_vt_is_left_alone(self, vt):
        display = GpuDisplay(NVIDIA)
        display._vt = 'tty2'
        display._starting()
