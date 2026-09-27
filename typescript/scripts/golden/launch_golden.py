#!/usr/bin/env python3
"""Record Python launch_options() outputs as goldens for the TypeScript port.

    .venv/bin/python typescript/scripts/golden/launch_golden.py

Writes typescript/tests/fixtures/launch/*.json, one file per scenario, and
typescript/tests/fixtures/launch/inputs.json (the fixed fingerprints / presets
the scenarios are built from). tests/launch-golden.test.ts replays every
scenario through the TypeScript launchOptions() and requires the same result.

Every source of nondeterminism is pinned, and every host probe is replaced, so
the goldens are a function of the code alone:

  * identity salt: scenarios pass a fixed fingerprint / preset dict (salt is a
    hash of it); the few that exercise the generate / random-preset paths patch
    the fresh salt, generate_fingerprint and get_random_preset.
  * host: XDG_CACHE_HOME points the camoufox cache at a scratch dir; the stock
    profile disk capacity, the host OS key, the host CPU count, the monitor
    probe and the public-IP lookup are patched; the GeoIP reader is a fake
    maxminddb module over a fixed table; numpy's weighted locale choice uses a
    fixed uniform draw (same algorithm as numpy, so the TS port can mirror it).
  * paths: the browser bundle is tests/fixtures/launch/bundle*, the cache the
    scratch dir; both are written back as <BUNDLE>/<CACHE>/... placeholders.

Recorded on Linux: OS_NAME affects the chunk size and the fontconfig, and the
TS test only replays on Linux.
"""

import copy
import io
import json
import os
import re
import sys
import tempfile
import types
import warnings
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
TS_ROOT = HERE.parent.parent
FIXTURES = TS_ROOT / 'tests' / 'fixtures' / 'launch'

# Must precede every camoufox import: INSTALL_DIR is computed at import time.
SCRATCH = Path(tempfile.mkdtemp(prefix='camoufox-golden-'))
os.environ['XDG_CACHE_HOME'] = str(SCRATCH / 'xdg-cache')
CACHE = SCRATCH / 'xdg-cache' / 'camoufox'
HOME = SCRATCH / 'home'
HOME.mkdir(parents=True)

# ---------------------------------------------------------------- fake GeoIP
GEO_TABLE = {
    '8.8.8.8': {'country_code': 'US', 'longitude': -97.822, 'latitude': 37.751, 'timezone': 'America/Chicago'},
    '81.2.69.160': {'country_code': 'GB', 'longitude': -0.0931, 'latitude': 51.5142, 'timezone': 'Europe/London'},
    '2a01:4f8::1': {'country_code': 'DE', 'longitude': 9.491, 'latitude': 51.2993, 'timezone': 'Europe/Berlin'},
    '203.0.113.7': {'country_code': 'JP', 'longitude': 139.6899, 'latitude': 35.6893, 'timezone': 'Asia/Tokyo'},
}
_fake_mmdb = types.ModuleType('maxminddb')


class _FakeReader:
    def __init__(self, path):
        self.path = path

    def get(self, ip):
        return copy.deepcopy(GEO_TABLE.get(ip))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_fake_mmdb.open_database = lambda path: _FakeReader(path)
sys.modules['maxminddb'] = _fake_mmdb

import numpy as np  # noqa: E402
import orjson  # noqa: E402

import camoufox.fingerprints as fingerprints  # noqa: E402
from camoufox import geolocation, locales, utils  # noqa: E402
from camoufox.addons import DefaultAddons  # noqa: E402
from camoufox.fingerprints import Screen  # noqa: E402
from camoufox.utils import launch_options  # noqa: E402

assert str(utils.INSTALL_DIR) == str(CACHE), (utils.INSTALL_DIR, CACHE)

# The mmdb files only have to exist and be fresh; the fake reader answers.
for name in ('maxmind geolite2-ipv4.mmdb', 'maxmind geolite2-ipv6.mmdb'):
    p = geolocation.MMDB_DIR / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'')

# The default addon, already "downloaded", so nothing is fetched.
(CACHE / 'addons' / 'UBO').mkdir(parents=True)
(CACHE / 'addons' / 'UBO' / 'manifest.json').write_text('{}')

# ------------------------------------------------------------ host probes
HOST = {
    'cpu_count': 16,
    'disk_capacity_kb': 250_000_000,
    'host_os_key': 'lin',
    'display': [1600, 900],
    'public_ip': '81.2.69.160',
    'locale_uniform': 0.5,
    'fresh_salt': 1234567890123456789,
}

fingerprints.host_cpu_count = lambda: HOST['cpu_count']
utils._stock_profile_disk_capacity_kb = lambda: HOST['disk_capacity_kb']
utils._host_os_key = lambda: HOST['host_os_key']
def _display():
    from camoufox.display import DisplaySize

    return DisplaySize(*HOST['display'])


utils.largest_display = _display
utils.public_ip = lambda proxy=None: HOST['public_ip']

_real_salt = utils.identity_salt
utils.identity_salt = lambda pinned=None: _real_salt(pinned) if pinned is not None else HOST['fresh_salt']


def _fixed_choice(a, p=None):
    # numpy.random.RandomState.choice(a, p=p), with the uniform draw pinned.
    cdf = np.cumsum(p)
    cdf /= cdf[-1]
    return a[int(cdf.searchsorted(HOST['locale_uniform'], side='right'))]


locales.np.random.choice = _fixed_choice

# ------------------------------------------------------------------ inputs
FPGEN_KEYS = ('navigator', 'screen', 'window', 'headers')


def js_equivalent(value):
    """What the value is once it has been through JSON in JavaScript: an
    integral float becomes an int, and a dict's array-index keys move to the
    front in ascending order (JS object key order)."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    if isinstance(value, dict):
        idx = sorted((k for k in value if isinstance(k, str) and _is_index(k)), key=int)
        rest = [k for k in value if k not in idx]
        return {k: js_equivalent(value[k]) for k in idx + rest}
    if isinstance(value, (list, tuple)):
        return [js_equivalent(v) for v in value]
    return value


def _is_index(k):
    return k.isdigit() and (k == '0' or not k.startswith('0')) and int(k) < 2**32 - 1


def make_fingerprint(os_name):
    fp = fingerprints._generator().generate(browser='Firefox', os=fingerprints._FPGEN_OS[os_name])
    fp = {k: fp[k] for k in FPGEN_KEYS if k in fp}
    # handle_screenXY draws screenY with randrange outside [-50, 50]
    fp.setdefault('window', {})['screenX'] = 0
    return js_equivalent(fp)


def load_inputs():
    path = FIXTURES / 'inputs.json'
    if path.exists() and '--regen-inputs' not in sys.argv:
        return json.loads(path.read_text())
    presets = orjson.loads((Path(fingerprints.__file__).parent / 'fingerprint-presets-v150.json').read_bytes())['presets']
    from camoufox.webgl import firefox_gpus

    pairs = {os_key: sorted(firefox_gpus(os_key)) for os_key in ('win', 'mac', 'lin')}
    known = {x for v in pairs.values() for x in v}

    def pick(os_key):
        for p in presets[os_key]:
            gl = p.get('webgl') or {}
            if (gl.get('unmaskedVendor'), gl.get('unmaskedRenderer')) in known:
                return p
        raise SystemExit(f'no preset for {os_key} with a recorded GPU')

    inputs = {
        'fingerprints': {o: make_fingerprint(o) for o in ('linux', 'windows', 'macos')},
        'presets': {
            'windows': pick('windows'),
            'macos': pick('macos'),
            'linux': pick('linux'),
            # A GPU fpgen has never seen, which launch_options must refuse.
            'windows_unknown_gpu': {**pick('windows'), 'webgl': {
                'unmaskedVendor': 'Google Inc. (Acme)',
                'unmaskedRenderer': 'ANGLE (Acme, Acme GPU 9000 Direct3D11 vs_5_0 ps_5_0)'}},
        },
        'webgl_pairs': {k: [list(x) for x in v[:2]] for k, v in pairs.items()},
    }
    inputs = js_equivalent(inputs)
    path.write_text(json.dumps(inputs, indent=1, ensure_ascii=False) + '\n')
    return inputs


INPUTS = load_inputs()

# ---------------------------------------------------------------- scenarios
BUNDLE = FIXTURES / 'bundle'
BUNDLE_OLD = FIXTURES / 'bundle-old'
ADDON = FIXTURES / 'addons' / 'example-addon'

PLACEHOLDERS = [
    (str(BUNDLE_OLD), '<BUNDLE_OLD>'),
    (str(BUNDLE), '<BUNDLE>'),
    (str(ADDON), '<ADDON>'),
    (str(CACHE), '<CACHE>'),
    (str(HOME), '<HOME>'),
]


def fill(value):
    """Scenario kwargs -> real values."""
    if isinstance(value, str):
        for real, ph in PLACEHOLDERS:
            value = value.replace(ph, real)
        return value
    if isinstance(value, dict):
        return {k: fill(v) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v) for v in value]
    return value


def mask(value):
    if isinstance(value, str):
        for real, ph in PLACEHOLDERS:
            value = value.replace(real, ph)
        # A FallbackWarning's report block names the host and the runtime
        # (python/node), so neither launcher can reproduce the other's.
        value = re.sub(r'(and include:\n\n)(    .*(\n|$))+', r'\1<REPORT>', value)
        # The name hashes the fonts.conf content, which embeds the checkout path;
        # the TS test masks it the same way and checks the hash itself.
        return re.sub(r'fonts-[0-9a-f]{12}\.conf', 'fonts-<HASH>.conf', value)
    if isinstance(value, dict):
        return {mask(k): mask(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask(v) for v in value]
    return value


BASE = {'executable_path': '<BUNDLE>/camoufox-bin', 'env': {'HOME': '<HOME>'}}
FP = INPUTS['fingerprints']
PR = INPUTS['presets']

S = {}


def scenario(name, _special=None, **kwargs):
    assert name not in S, name
    S[name] = {'kwargs': {**BASE, **kwargs}, 'special': _special or {}}


# fpgen fingerprints, one per target OS
for _os in ('linux', 'windows', 'macos'):
    scenario(f'fpgen_{_os}', fingerprint=FP[_os], os=_os)
scenario('fpgen_linux_ikwid', fingerprint=FP['linux'], os='linux', i_know_what_im_doing=True)
scenario('fpgen_no_os', fingerprint=FP['windows'])
scenario('fpgen_os_list', fingerprint=FP['macos'], os=['macos', 'windows'])

# presets
for _os in ('windows', 'macos', 'linux'):
    scenario(f'preset_{_os}', fingerprint_preset=PR[_os])
scenario('preset_windows_unknown_gpu', fingerprint_preset=PR['windows_unknown_gpu'])
scenario('preset_random', {'random_preset': 'macos'}, fingerprint_preset=True, os='macos')

# generation path (generate_fingerprint patched to a fixed fingerprint)
scenario('generate_default', {'generate': 'linux'})
scenario('generate_window', {'generate': 'windows'}, window=[1280, 720], os='windows')
scenario('generate_screen', {'generate': 'macos'}, screen={'max_width': 1920, 'max_height': 1080}, os='macos')
scenario('generate_headful_display', {'generate': 'linux'}, headless=False,
         env={'HOME': '<HOME>', 'DISPLAY': ':0'})
scenario('generate_headless_display', {'generate': 'linux'}, headless=True,
         env={'HOME': '<HOME>', 'DISPLAY': ':0'})

# headless / display handling on a fixed identity
scenario('headful_display_clamp', fingerprint=FP['windows'], os='windows', headless=False,
         env={'HOME': '<HOME>', 'DISPLAY': ':0'})
scenario('headless_true', fingerprint=FP['linux'], os='linux', headless=True)
scenario('virtual_display', fingerprint=FP['linux'], os='linux', virtual_display=':99',
         env={'HOME': '<HOME>', 'WAYLAND_DISPLAY': 'wayland-0', 'GDK_BACKEND': 'wayland', 'KEEP': '1'})

# locale
scenario('locale_full', fingerprint=FP['linux'], os='linux', locale='fr-FR')
scenario('locale_script', fingerprint=FP['linux'], os='linux', locale='zh-Hans-CN')
scenario('locale_language_only', fingerprint=FP['windows'], os='windows', locale='de')
scenario('locale_region_only', fingerprint=FP['windows'], os='windows', locale='CA')
scenario('locale_list', fingerprint=FP['macos'], os='macos', locale=['en-US', 'fr-FR', 'de', 'en-US'])
scenario('locale_string_list', fingerprint=FP['macos'], os='macos', locale='ja-JP, en')
scenario('locale_invalid', fingerprint=FP['linux'], os='linux', locale='xx-invalid-tag-!!')

# geoip / proxy
scenario('geoip_ipv4', fingerprint=FP['windows'], os='windows', geoip='8.8.8.8')
scenario('geoip_ipv6', fingerprint=FP['windows'], os='windows', geoip='2a01:4f8::1')
scenario('geoip_true_proxy', fingerprint=FP['linux'], os='linux', geoip=True,
         proxy={'server': 'http://proxy.example:8080', 'username': 'u', 'password': 'p'})
scenario('geoip_true_no_proxy', fingerprint=FP['linux'], os='linux', geoip=True)
scenario('geoip_block_webrtc', fingerprint=FP['macos'], os='macos', geoip='203.0.113.7', block_webrtc=True)
scenario('geoip_with_locale', fingerprint=FP['macos'], os='macos', geoip='8.8.8.8', locale='es-MX')
scenario('geoip_manual_timezone', fingerprint=FP['macos'], os='macos', geoip='8.8.8.8',
         config={'timezone': 'Europe/Paris', 'locale:language': 'fr', 'locale:region': 'FR'})
scenario('geoip_db_named', fingerprint=FP['linux'], os='linux', geoip='8.8.8.8', geoip_db='MaxMind GeoLite2')
scenario('geoip_unknown_ip', fingerprint=FP['linux'], os='linux', geoip='192.0.2.1')
scenario('geoip_invalid_ip', fingerprint=FP['linux'], os='linux', geoip='not-an-ip')
scenario('proxy_without_geoip', fingerprint=FP['linux'], os='linux', proxy={'server': 'http://proxy.example:8080'})
scenario('proxy_localhost', fingerprint=FP['linux'], os='linux', proxy={'server': 'http://localhost:8080'})
scenario('proxy_manual_geolocation', fingerprint=FP['linux'], os='linux', proxy={'server': 'socks5://1.2.3.4:1080'},
         config={'geolocation:latitude': 10.5, 'geolocation:longitude': 20.25})

# humanize
scenario('humanize_true', fingerprint=FP['linux'], os='linux', humanize=True)
scenario('humanize_float', fingerprint=FP['linux'], os='linux', humanize=1.5)
scenario('humanize_int', fingerprint=FP['linux'], os='linux', humanize=2)
scenario('humanize_false', fingerprint=FP['linux'], os='linux', humanize=False)

# block_* and friends
scenario('block_all', fingerprint=FP['windows'], os='windows', block_images=True, block_webrtc=True,
         block_webgl=True, disable_coop=True)
scenario('block_all_ikwid', fingerprint=FP['windows'], os='windows', block_images=True, block_webrtc=True,
         block_webgl=True, disable_coop=True, i_know_what_im_doing=True)
scenario('allow_webgl_false', fingerprint=FP['linux'], os='linux', allow_webgl=False)
scenario('flags', fingerprint=FP['macos'], os='macos', main_world_eval=True, allow_addon_new_tab=True,
         enable_cache=True, args=['--foo', '--bar=1'], firefox_user_prefs={'my.pref': 'x', 'ui.useOverlayScrollbars': 0,
                                                                          'intl.locale.requested': 'de-DE'})
scenario('ff_version', fingerprint=FP['windows'], os='windows', ff_version=140)
scenario('pin_cpu_cores', fingerprint=FP['linux'], os='linux', pin_cpu_cores=True)

# addons
scenario('addons_custom', fingerprint=FP['linux'], os='linux', addons=['<ADDON>'])
scenario('addons_exclude_default', fingerprint=FP['linux'], os='linux', exclude_addons=['UBO'])
scenario('addons_only_custom', fingerprint=FP['linux'], os='linux', addons=['<ADDON>'], exclude_addons=['UBO'])
scenario('addons_invalid', fingerprint=FP['linux'], os='linux', addons=['<BUNDLE>/fonts'])

# webgl
scenario('webgl_config_windows', fingerprint=FP['windows'], os='windows', webgl_config=INPUTS['webgl_pairs']['win'][0])
scenario('webgl_config_macos', fingerprint=FP['macos'], os='macos', webgl_config=INPUTS['webgl_pairs']['mac'][0])
scenario('webgl_config_no_os', fingerprint=FP['linux'], webgl_config=INPUTS['webgl_pairs']['lin'][0])
scenario('webgl_config_unknown', fingerprint=FP['linux'], os='linux', webgl_config=['Nope', 'Nope GPU'])

# fonts / voices
scenario('fonts_custom', fingerprint=FP['linux'], os='linux', fonts=['Arial', 'Helvetica', 'Comic Sans MS'])
scenario('fonts_custom_only', fingerprint=FP['windows'], os='windows', fonts=['Arial'], custom_fonts_only=True)
scenario('fonts_custom_only_missing', fingerprint=FP['windows'], os='windows', custom_fonts_only=True)
scenario('fonts_config', fingerprint=FP['macos'], os='macos', config={'fonts': ['Helvetica', 'Menlo']})
scenario('fonts_config_empty', fingerprint=FP['macos'], os='macos', config={'fonts': []})
scenario('voices_config', fingerprint=FP['macos'], os='macos', config={'voices': [
    {'lang': 'en-US', 'name': 'Samantha', 'voiceUri': 'com.apple.voice.compact.en-US.Samantha', 'isDefault': True,
     'isLocalService': True}]})
scenario('voices_config_bad', fingerprint=FP['macos'], os='macos', config={'voices': ['Samantha:en-US:local']})
scenario('voices_config_missing_field', fingerprint=FP['macos'], os='macos', config={'voices': [{'lang': 'en-US'}]})

# config overrides and the warnings they emit
scenario('config_navigator', fingerprint=FP['windows'], os='windows',
         config={'navigator.userAgent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0',
                 'navigator.platform': 'Win32', 'navigator.hardwareConcurrency': 6})
scenario('config_ua_only', {'generate': 'macos'}, config={
    'navigator.userAgent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0'})
scenario('config_ua_ikwid', {'generate': 'linux'}, i_know_what_im_doing=True, config={
    'navigator.userAgent': 'Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0'})
scenario('config_header_ua', fingerprint=FP['linux'], os='linux', config={'headers.User-Agent': 'x'})
scenario('config_locale_keys', fingerprint=FP['linux'], os='linux',
         config={'locale:language': 'pt', 'locale:region': 'BR', 'headers.Accept-Language': 'pt-BR'})
scenario('config_screen', fingerprint=FP['macos'], os='macos',
         config={'screen.width': 1440, 'screen.height': 900, 'window.outerWidth': 1200})
scenario('config_touch', fingerprint=FP['windows'], os='windows', config={'navigator.maxTouchPoints': 5})
scenario('config_dnt_gpc', fingerprint=FP['windows'], os='windows',
         config={'navigator.doNotTrack': '1', 'navigator.globalPrivacyControl': True})
scenario('config_accept_encoding', fingerprint=FP['linux'], os='linux', config={'headers.Accept-Encoding': 'gzip'})
scenario('config_seeds', fingerprint=FP['linux'], os='linux', config={'audio:seed': 42})
scenario('config_instant_animations', fingerprint=FP['linux'], os='linux', config={'instantAnimations': True})
scenario('config_media_devices', fingerprint=FP['linux'], os='linux', config={'mediaDevices:micros': 0})
scenario('config_webgl_pair', fingerprint=FP['linux'], os='linux',
         config={'webGl:vendor': INPUTS['webgl_pairs']['lin'][1][0], 'webGl:renderer': INPUTS['webgl_pairs']['lin'][1][1]})
scenario('config_webgl_unknown_pair', fingerprint=FP['linux'], os='linux',
         config={'webGl:vendor': 'Nope', 'webGl:renderer': 'Nope GPU'})
scenario('config_unknown_key', fingerprint=FP['linux'], os='linux',
         config={'not.a.real.property': {'a': [1, 'b', None, True]}, 'also.unknown': 'x'})
scenario('config_bad_type', fingerprint=FP['linux'], os='linux', config={'navigator.buildID': 5})
scenario('config_float_int', fingerprint=FP['linux'], os='linux', config={'screen.width': 1920.0,
                                                                          'window.devicePixelRatio': 2})
scenario('config_non_ascii', fingerprint=FP['linux'], os='linux', config={'timezone': 'America/São_Paulo'},
         firefox_user_prefs={'my.unicode.pref': 'héllo ✓ \U0001F600'})

# errors / validation
scenario('invalid_os_case', fingerprint=FP['linux'], os='Linux')
scenario('invalid_os_name', fingerprint=FP['linux'], os='beos')
scenario('non_firefox_fingerprint', fingerprint={**FP['linux'], 'navigator': {
    **FP['linux']['navigator'], 'userAgent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}})

# persistent context / passthrough Playwright options
scenario('persistent_passthrough', fingerprint=FP['linux'], os='linux', user_data_dir='<HOME>/profile',
         slow_mo=50, timeout=12345)

# executable_path handling
scenario('executable_old_build', fingerprint=FP['linux'], os='linux', executable_path='<BUNDLE_OLD>/camoufox-bin')
scenario('executable_from_env', {'process_env': {'CAMOUFOX_EXECUTABLE_PATH': '<BUNDLE>/camoufox-bin'}},
         fingerprint=FP['linux'], os='linux', executable_path=None)

# chunking: a config bigger than one env var chunk
scenario('config_large', fingerprint=FP['linux'], os='linux', i_know_what_im_doing=True,
         config={'fonts': [f'Font Family {i:05d}' for i in range(2600)]})


# ------------------------------------------------------------------ running
def run(name, spec):
    kwargs = fill(copy.deepcopy(spec['kwargs']))
    special = spec['special']
    calls = []
    restore = []

    if kwargs.get('executable_path') is None:
        kwargs.pop('executable_path', None)
    if 'screen' in kwargs:
        kwargs['screen'] = Screen(**kwargs['screen'])
    if 'exclude_addons' in kwargs:
        kwargs['exclude_addons'] = [DefaultAddons[x] for x in kwargs['exclude_addons']]
    if 'webgl_config' in kwargs:
        kwargs['webgl_config'] = tuple(kwargs['webgl_config'])
    if 'window' in kwargs:
        kwargs['window'] = tuple(kwargs['window'])

    if 'generate' in special:
        base_fp = FP[special['generate']]

        def fake_generate(window=None, screen=None, os=None, **conditions):
            calls.append({'fn': 'generate_fingerprint', 'window': list(window) if window else None,
                          'screen': None if screen is None else {k: getattr(screen, k) for k in (
                              'min_width', 'max_width', 'min_height', 'max_height')},
                          'os': os})
            fp = copy.deepcopy(base_fp)
            if window:
                fingerprints.handle_window_size(fp, *window)
            return fp

        restore.append(('generate_fingerprint', utils.generate_fingerprint))
        utils.generate_fingerprint = fake_generate
    if 'random_preset' in special:
        preset = PR[special['random_preset']]

        def fake_random_preset(os=None, ff_version=None):
            calls.append({'fn': 'get_random_preset', 'os': os, 'ff_version': ff_version})
            return copy.deepcopy(preset)

        restore.append(('get_random_preset', utils.get_random_preset))
        utils.get_random_preset = fake_random_preset
    env_backup = {}
    for k, v in special.get('process_env', {}).items():
        env_backup[k] = os.environ.get(k)
        os.environ[k] = fill(v)

    out = io.StringIO()
    record = {'name': name, 'kwargs': spec['kwargs'], 'special': special}
    try:
        with warnings.catch_warnings(record=True) as caught, redirect_stdout(out):
            warnings.simplefilter('always')
            try:
                result = launch_options(**kwargs)
            except Exception as exc:  # recorded, not raised
                record['error'] = {'type': type(exc).__name__, 'message': mask(str(exc))}
                result = None
        record['warnings'] = [{'category': w.category.__name__, 'message': mask(str(w.message))} for w in caught]
    finally:
        for attr, value in restore:
            setattr(utils, attr, value)
        for k, v in env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    record['stdout'] = mask(out.getvalue())
    record['calls'] = mask(calls)
    if result is not None:
        record['result'] = describe(result)
    return record


def describe(result):
    env = dict(result['env'])
    config_chunks = sorted(((int(k.rsplit('_', 1)[1]), k) for k in env if k.startswith('CAMOU_CONFIG_')))
    pref_chunks = sorted(((int(k.rsplit('_', 1)[1]), k) for k in env if k.startswith('CAMOU_PREFS_')))
    config_blob = ''.join(env[k] for _, k in config_chunks)
    prefs_blob = ''.join(env[k] for _, k in pref_chunks)
    fontconfig = None
    if 'FONTCONFIG_FILE' in env:
        fontconfig = {'path': mask(env['FONTCONFIG_FILE']), 'content': mask(Path(env['FONTCONFIG_FILE']).read_text())}
    other_env = {k: v for k, v in env.items() if not k.startswith(('CAMOU_CONFIG_', 'CAMOU_PREFS_'))}
    rest = {k: v for k, v in result.items() if k not in ('env',)}
    config = orjson.loads(config_blob)
    js_blob = mask(orjson.dumps(js_equivalent(config)).decode())
    return {
        'options': mask(js_equivalent(rest)),
        'env': mask(other_env),
        'config_chunks': [len(env[k]) for _, k in config_chunks],
        'prefs_chunks': [len(env[k]) for _, k in pref_chunks],
        # The config as JavaScript serializes the same data (see js_equivalent);
        # the raw Python blob too, only when it differs from that.
        'config_blob_js': js_blob,
        **({'config_blob_raw': mask(config_blob)} if mask(config_blob) != js_blob else {}),
        'prefs_blob': prefs_blob,
        'fontconfig': fontconfig,
    }


def main():
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    for old in FIXTURES.glob('scenario-*.json'):
        if not only:
            old.unlink()
    summary = {'host': HOST, 'geo_table': GEO_TABLE, 'scenarios': []}
    for name, spec in S.items():
        if only and name not in only:
            continue
        rec = run(name, spec)
        (FIXTURES / f'scenario-{name}.json').write_text(json.dumps(rec, indent=1, ensure_ascii=False) + '\n')
        summary['scenarios'].append(name)
        status = rec.get('error', {}).get('type', 'ok')
        print(f'{name:32s} {status:24s} warnings={len(rec["warnings"])}', file=sys.stderr)
    if not only:
        (FIXTURES / 'host.json').write_text(json.dumps(summary, indent=1) + '\n')


if __name__ == '__main__':
    main()
