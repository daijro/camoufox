#!/usr/bin/env python3
"""Record the Python identity layer's outputs as goldens for the TypeScript port.

    .venv/bin/python typescript/scripts/golden/identity_golden.py

Writes typescript/tests/fixtures/identity/*.json (and one .json.gz holding full
fpgen fingerprints). tests/identity-golden.test.ts replays every case through
the TypeScript functions and requires the identical result.

Everything recorded is a pure function of its recorded inputs: seeded draws
take their seed from the case, the unseeded module-level `random` is re-seeded
per case (the TS side seeds its `pyRandom` the same way), and the host probes
fix_hardware_concurrency reads are patched. Large outputs (font / voice lists,
WebGL parameter blobs, preset configs) are recorded as a short hash:

    sha256(orjson.dumps(canon(value), OPT_SORT_KEYS)).hexdigest()[:20]

where canon() turns integral floats below 2**53 into ints and ints from 2**53
up into floats (JavaScript cannot tell 1.0 from 1 once parsed, nor keep an int
past 2**53 exact, so the TS side hashes the same canonical form).
"""

import copy
import gzip
import hashlib
import json
import math
import random
import sys
import zlib
from pathlib import Path
from unittest import mock

import numpy as np
import orjson

HERE = Path(__file__).resolve().parent
TS_ROOT = HERE.parent.parent
FIXTURES = TS_ROOT / 'tests' / 'fixtures' / 'identity'
sys.path.insert(0, str(HERE))

import pyrandom_cases  # noqa: E402

from camoufox import coherence  # noqa: E402
from camoufox import cpu_affinity  # noqa: E402
from camoufox import fingerprints as fp  # noqa: E402
from camoufox import webgl  # noqa: E402

OS_NAMES = ('windows', 'macos', 'linux')
OS_KEYS = ('win', 'mac', 'lin')


def canon(o):
    if isinstance(o, bool) or o is None:
        return o
    if isinstance(o, float) and o.is_integer() and abs(o) < 2**53:
        return int(o)
    if isinstance(o, int) and abs(o) >= 2**53:
        return float(o)  # a JavaScript number past 2**53 is a float either way
    if isinstance(o, dict):
        return {str(k): canon(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [canon(v) for v in o]
    return o


def h(o) -> str:
    return hashlib.sha256(orjson.dumps(canon(o), option=orjson.OPT_SORT_KEYS)).hexdigest()[:20]


def write(name, data, compress=True):
    """Write a fixture; the large ones gzipped (mtime 0, so reruns are byte-stable)."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n'
    path = FIXTURES / (name + '.gz' if compress else name)
    if compress:
        path.write_bytes(gzip.compress(text.encode('utf-8'), compresslevel=9, mtime=0))
    else:
        path.write_text(text, encoding='utf-8')
    print(f'{path.relative_to(TS_ROOT)}: {path.stat().st_size // 1024} KiB')


def hashed_lists(config):
    """A config with its (long) font and voice lists replaced by their hashes."""
    out = dict(config)
    for key in ('fonts', 'voices'):
        if key in out:
            out[key] = {'hash': h(out[key]), 'len': len(out[key])}
    return out


def err(fn):
    try:
        return {'ok': fn()}
    except Exception as exc:  # noqa: BLE001
        return {'error': type(exc).__name__, 'message': str(exc)}


# ---------------------------------------------------------------------------
# pyrandom + numpy + python-compat primitives
# ---------------------------------------------------------------------------


def record_pyrandom():
    write('pyrandom.json', {'cases': pyrandom_cases.cases()})


def record_numpy():
    """np.sum over a float64 array, which the locale selector normalises by."""
    rng = random.Random(20260924)
    sums = []
    for n in (0, 1, 2, 5, 7, 8, 9, 15, 16, 17, 31, 64, 100, 127, 128, 129, 200, 255, 256, 257, 600):
        vals = [rng.uniform(-1, 1) * 10 ** rng.randint(-8, 8) for _ in range(n)]
        sums.append({'values': vals, 'sum': float(np.array(vals, dtype=np.float64).sum())})
    write('numpy.json', {'sums': sums})


SALT_OBJECTS = [
    {},
    {'a': 1, 'b': 2},
    {'b': 2, 'a': 1},
    {'nested': {'z': [1, 2.5, None, True, False], 'a': 'x'}, 'k': -0.0},
    {'floats': [1.0, 0.1, 1e16, 1e15, 1.5e-7, 1e-5, 1e-6, 3.4028234663852886e38, -2.5e-310, 123456.789, 1e21]},
    {'big': 18446744073709551615, 'neg': -9223372036854775808, 'safe': 9007199254740993},
    {'unicode': 'é😀 \x00\x1f"\\/', 'é': 1, '😀': 2, '￿': 3, 'Z': 4, 'a': 5},
    {'navigator.userAgent': 'Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0',
     'screen.width': 1920, 'screen.height': 1080, 'window.devicePixelRatio': 1.0},
    ['list', 'at', 'top', 1, 2.0],
    'a plain string',
    12345,
    1.0,
    None,
]


def record_pycompat():
    rng = random.Random(1717)
    floats = [0.0, -0.0, 1.0, -1.0, 0.1, 0.5, 1e16, 1e15, 9999999999999998.0, 1.0000000000000002e16,
              123456789012345678.0, 1.5e-7, 1e-5, 1.5e-5, 9.99e-6, 1e-4, 1e-6, 0.000123, 1e21, 1e22, 1e100,
              3.4028234663852886e38, 5e-324, 1.7976931348623157e308, 12345.678, 9007199254740992.0,
              9223372034707292000.0, 1.8446744073709552e19, 2.5, 100.0, 1e-7, 1.234e-300]
    for _ in range(300):
        floats.append(rng.uniform(-1, 1) * 10 ** rng.randint(-30, 30))
    for _ in range(60):
        floats.append(float(rng.randint(-10**18, 10**18)))
    float_cases = [[x, orjson.dumps(x).decode(), repr(x)] for x in floats]

    sums = []
    for _ in range(150):
        n = rng.randint(0, 25)
        items = []
        for _ in range(n):
            kind = rng.random()
            if kind < 0.25:
                items.append(rng.randint(-100, 100))
            elif kind < 0.6:
                items.append(rng.uniform(-1, 1) * 10 ** rng.randint(-20, 20))
            else:
                items.append(rng.random())
        result = sum(items)
        sums.append({
            'items': [{'i': x} if isinstance(x, int) else {'f': x} for x in items],
            'result': {'i': result} if isinstance(result, int) else {'f': result},
        })
    float_sums = []
    for _ in range(150):
        vals = [rng.random() * rng.choice([1, 1e-3, 1e10, 1e-17, 3]) for _ in range(rng.randint(1, 40))]
        float_sums.append({'values': vals, 'sum': sum(vals)})

    crc = [[s, zlib.crc32(s.encode('utf-8'))] for s in ('', 'a', 'hello world', 'é😀', 'x' * 1000)]

    salts = [{'value': o, 'salt': str(fp.identity_salt(o))} for o in SALT_OBJECTS]
    salts.append({'screen': [1, 2, 3, 4], 'salt': str(fp.identity_salt(fp.Screen(1, 2, 3, 4)))})
    salts.append({'screen': [None, 1920, None, 1080], 'salt': str(fp.identity_salt(fp.Screen(None, 1920, None, 1080)))})

    seeds = []
    configs = [
        {},
        {'navigator.userAgent': 'x', 'navigator.platform': 'Win32', 'screen.width': 1920,
         'screen.height': 1080, 'navigator.hardwareConcurrency': 8},
        {'navigator.userAgent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0',
         'navigator.platform': 'MacIntel', 'screen.width': 1512.5, 'screen.height': None,
         'navigator.hardwareConcurrency': True},
        {'navigator.userAgent': 'é😀', 'screen.width': 0, 'screen.height': ''},
        {'navigator.platform': 1e-5, 'screen.width': 1e16, 'navigator.hardwareConcurrency': -3},
    ]
    for c in configs:
        for salt in (0, 1, 2**31, 2**64 - 1, 12345678901234567890):
            seeds.append({'config': c, 'salt': str(salt), 'seed': fp.identity_seed(c, salt)})

    reprs = [[s, repr(s)] for s in ('', 'abc', "it's", 'say "hi"', 'both \' and "', 'tab\there', 'nl\n',
                                     'back\\slash', '\x00\x7f', 'é😀', '​', ' ', 'Apple M1, or similar')]
    write('pycompat.json', {'floats': float_cases, 'sums': sums, 'floatSums': float_sums, 'crc32': crc,
                            'salts': salts, 'seeds': seeds, 'reprs': reprs,
                            'python': list(sys.version_info[:2])})


def record_fpgen_salts():
    """Full fpgen fingerprints (one per OS, plus one carrying an int > 2**53)."""
    found = {}
    tries = 0
    while len(found) < 4 and tries < 200:
        tries += 1
        os_name = OS_NAMES[tries % 3]
        f = fp.generate_fingerprint(os=os_name)
        big = isinstance(((f.get('webgl2') or {}).get('params') or {}).get('37137', {}).get('value'), int)
        if os_name not in found:
            found[os_name] = f
        elif big and 'bigint' not in found:
            found['bigint'] = f
    cases = [{'label': k, 'fingerprint': v, 'salt': str(fp.identity_salt(v))} for k, v in found.items()]
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / 'fpgen-salts.json.gz'
    path.write_bytes(gzip.compress(json.dumps(cases, ensure_ascii=False).encode('utf-8'), mtime=0))
    print(f'{path.relative_to(TS_ROOT)}: {path.stat().st_size // 1024} KiB')


# ---------------------------------------------------------------------------
# per-identity draws
# ---------------------------------------------------------------------------


def record_fonts():
    cases = []
    for os_name in OS_NAMES + ('plan9',):
        for seed in range(150):
            locale = None if seed < 100 else ('zh-TW' if seed < 125 else 'en-US')
            fonts = fp._generate_random_font_subset(os_name, seed=seed, locale=locale)
            case = {'os': os_name, 'seed': seed, 'locale': locale, 'hash': h(fonts), 'len': len(fonts)}
            if seed < 2:
                case['fonts'] = fonts
            cases.append(case)
        for seed in (2**32 - 1, 2**40 + 3):
            fonts = fp._generate_random_font_subset(os_name, seed=seed)
            cases.append({'os': os_name, 'seed': str(seed), 'locale': None, 'hash': h(fonts), 'len': len(fonts)})
        fonts = fp._generate_random_font_subset(os_name, seed=0, native=True)
        cases.append({'os': os_name, 'seed': 0, 'native': True, 'locale': None, 'hash': h(fonts),
                      'len': len(fonts), 'fonts': fonts})
    write('fonts.json', {'cases': cases})


VOICE_LOCALES = (None, 'en-US', 'en-GB', 'de-DE', 'fr-FR', 'zh-TW', 'ja-JP', 'pt-BR', 'es', 'xx-YY')


def manifest_voice_entries(node):
    """Every "Name:lang:type" entry in a voice manifest, in document order."""
    if isinstance(node, dict):
        return [e for value in node.values() for e in manifest_voice_entries(value)]
    if isinstance(node, list):
        return [e for item in node
                for e in ([item] if isinstance(item, str) and item.count(':') >= 2
                          else manifest_voice_entries(item))]
    return []


def record_voices():
    cases = []
    for os_name in OS_NAMES + ('plan9',):
        for locale in VOICE_LOCALES:
            for seed in range(20):
                voices = fp._generate_random_voice_subset(os_name, locale, seed=seed)
                case = {'os': os_name, 'locale': locale, 'seed': seed, 'hash': h(voices), 'len': len(voices)}
                if seed == 0 and locale in (None, 'de-DE'):
                    case['voices'] = voices
                cases.append(case)
    uris = []
    uri_hashes = {}
    for os_key, manifest in fp._load_voice_manifests().items():
        entries = manifest_voice_entries(manifest)
        per = []
        for entry in entries:
            name, lang, _ = entry.rsplit(':', 2)
            per.append(fp._voice_uri(os_key, name, lang))
        uri_hashes[os_key] = h(per)
        for entry in entries[:: max(1, len(entries) // 15)]:
            name, lang, _ = entry.rsplit(':', 2)
            uris.append([os_key, name, lang, fp._voice_uri(os_key, name, lang)])
    for os_key in ('mac', 'win', 'lin', 'xx'):
        for name, lang in (('Albert', 'en-US'), ('Eddy', 'de-DE'), ('Zoë Ünïcode', 'fr-FR'),
                           ('Some Voice (Enhanced)', 'en-GB'), ('日本語', 'ja-JP'), ('.Dots.', 'en')):
            uris.append([os_key, name, lang, fp._voice_uri(os_key, name, lang)])
    normalized = []
    for fname in ('fingerprint-presets.json', 'fingerprint-presets-v150.json'):
        presets = json.loads((Path(fp.__file__).parent / fname).read_text())['presets']
        for os_name, entries in presets.items():
            for i, preset in enumerate(entries):
                if preset.get('speechVoices'):
                    out = fp._normalize_preset_voices(preset['speechVoices'], os_name)
                    normalized.append({'file': fname, 'os': os_name, 'index': i, 'hash': h(out), 'len': len(out)})
    extra = ['Albert:en-US:local', 'bad', 'x:y', ':en:local', 'Name::local', 'A:b:c:remote',
             {'name': 'Obj', 'lang': 'en', 'voiceUri': 'u', 'isDefault': False, 'isLocalService': True}]
    normalized.append({'extra': extra, 'os': 'macos', 'out': fp._normalize_preset_voices(extra, 'macos')})
    write('voices.json', {'cases': cases, 'uris': uris, 'uriHashes': uri_hashes, 'normalized': normalized})


def record_media():
    cases = []
    for os_key in OS_KEYS + ('xx',):
        for seed in range(150):
            out = fp.draw_media_devices(os_key, seed)
            case = {'os': os_key, 'seed': seed, 'hash': h(out)}
            if seed < 4:
                case['out'] = out
            cases.append(case)
    defaults = []
    for i in range(60):
        plat = ('Win32', 'MacIntel', 'Linux x86_64', '', None)[i % 5]
        config = {'navigator.userAgent': f'ua{i}', 'screen.width': 1920}
        if plat is not None:
            config['navigator.platform'] = plat
        salt = (0, 7, 2**64 - 1)[i % 3]
        before = copy.deepcopy(config)
        fp.set_media_devices_defaults(config, salt)
        defaults.append({'config': before, 'salt': str(salt), 'hash': h(config)})
    preset_mix = {'mediaDevices:webcams': 5, 'navigator.platform': 'Win32'}
    before = copy.deepcopy(preset_mix)
    fp.set_media_devices_defaults(preset_mix)
    defaults.append({'config': before, 'salt': '0', 'hash': h(preset_mix)})
    write('media.json', {'cases': cases, 'defaults': defaults})


def exact(o) -> str:
    """sha256 of the exact orjson bytes: key order, int vs float and all."""
    return hashlib.sha256(orjson.dumps(o)).hexdigest()[:20]


WEBGL_SCREENS = [(1024, 600), (800, 480), (1366, 768), (1280, 800), (1920, 1080), (2560, 1440), (None, None)]


def record_webgl():
    gpus = {os_key: [[r.value['vendor'], r.value['renderer']] for r in webgl._trace('gpu', os_key)]
            for os_key in OS_KEYS}

    for_screen = []
    for os_key in OS_KEYS:
        for w, hh in WEBGL_SCREENS:
            for seed in range(60):
                out = webgl.sample_webgl_for_screen(os_key, w, hh, seed=seed)
                for_screen.append({'os': os_key, 'w': w, 'h': hh, 'seed': str(seed),
                                   'renderer': out['webGl:renderer'], 'hash': exact(out)})
        for seed in (2**32 - 1, 2**40, 2**64 + 1, 12345678901234567890123):
            out = webgl.sample_webgl_for_screen(os_key, 1920, 1080, seed=seed)
            for_screen.append({'os': os_key, 'w': 1920, 'h': 1080, 'seed': str(seed),
                               'renderer': out['webGl:renderer'], 'hash': exact(out)})

    # The core count and a notched panel narrow the macOS draw.
    for_machine = []
    for cores in (8, 20, 22):
        for w, hh in ((2560, 1440), (1470, 956)):
            for seed in range(20):
                out = webgl.sample_webgl_for_screen('mac', w, hh, seed=seed, cores=cores)
                for_machine.append({'os': 'mac', 'w': w, 'h': hh, 'seed': str(seed), 'cores': cores,
                                    'renderer': out['webGl:renderer'], 'hash': exact(out)})

    # Every GPU fpgen records for each OS, and every bundled preset's GPU.
    for_gpu = []
    targets = {(os_key, v, r) for os_key in OS_KEYS for v, r in gpus[os_key]}
    for fname in ('fingerprint-presets.json', 'fingerprint-presets-v150.json'):
        presets = json.loads((Path(fp.__file__).parent / fname).read_text())['presets']
        for os_name, entries in presets.items():
            os_key = {'windows': 'win', 'macos': 'mac', 'linux': 'lin'}[os_name]
            for preset in entries:
                targets.add((os_key, preset['webgl']['unmaskedVendor'], preset['webgl']['unmaskedRenderer']))
    for os_key, v, r in sorted(targets):
        for seed in range(5):
            for_gpu.append({'os': os_key, 'vendor': v, 'renderer': r, 'seed': seed,
                            **err(lambda: exact(webgl.webgl_for_gpu(os_key, v, r, seed=seed)))})
    for os_key, v, r in (('win', 'Nope', 'Nope GPU'), ('lin', 'Apple', 'Apple M1, or similar')):
        for_gpu.append({'os': os_key, 'vendor': v, 'renderer': r, 'seed': 0,
                        **err(lambda: webgl.webgl_for_gpu(os_key, v, r, seed=0))})
    errors = {
        'unknownOs': err(lambda: webgl.sample_webgl_for_screen('bsd', 1920, 1080, seed=0)),
    }

    recorded = {
        'vendor': 'v', 'renderer': 'r', 'contextAttributes': {'alpha': True}, 'params': {'3379': {'value': 1.0}},
        'shaderPrecisionFormats': [{'shaderType': 35633, 'precisionType': 36336,
                                    'shaderPrecisionFormat': {'rangeMin': 127, 'rangeMax': 127, 'precision': 23}}],
        'supportedExtensions': ['ANGLE_instanced_arrays', 'WEBGL_multi_draw', 'OVR_multiview2',
                                'WEBGL_compressed_texture_etc1'],
    }
    recorded2 = {**recorded, 'supportedExtensions': ['EXT_texture_norm16', 'WEBGL_clip_cull_distance',
                                                     'OVR_multiview2', 'EXT_color_buffer_float']}
    converted = [{'os': os_key, 'webgl2': w2, 'hash': exact(webgl.to_config(recorded, w2, os_key))}
                 for os_key in OS_KEYS for w2 in (recorded2, [])]

    write('webgl.json', {'gpus': gpus, 'forScreen': for_screen, 'forMachine': for_machine, 'forGpu': for_gpu,
                         'errors': errors, 'recorded': recorded, 'recorded2': recorded2, 'converted': converted})


# ---------------------------------------------------------------------------
# geometry fixes + coherence
# ---------------------------------------------------------------------------


def maybe(rng, value, p_missing=0.15, p_none=0.03):
    roll = rng.random()
    if roll < p_missing:
        return '__missing__'
    if roll < p_missing + p_none:
        return None
    return value


def random_geometry(rng, p_none=0.03):
    sw = rng.choice([800, 1024, 1280, 1366, 1440, 1536, 1600, 1920, 2560, 3440, 3840, 736, 1080])
    sh = rng.choice([480, 600, 720, 768, 800, 864, 900, 1024, 1080, 1440, 1600, 2160, 414, 1920])
    aw = sw - rng.choice([0, 0, 0, 40, 60, -30])
    ah = sh - rng.choice([0, 0, 25, 27, 40, 48, -20, 900])
    ow = rng.choice([sw, sw - 100, sw + 200, 1280, 800, 0])
    oh = rng.choice([sh, ah, sh - 40, sh + 100, 720, 1000, 0])
    iw = ow - rng.choice([0, 16, -20, 200, 0])
    ih = oh - rng.choice([0, 74, 86, 90, 120, -10, 2000])
    sx = rng.choice([0, 0, 8, -8, 60, 250, -200, 5000])
    sy = rng.choice([0, 0, 20, 281, -30, 900])
    c = {}
    for key, value in (('screen.width', sw), ('screen.height', sh), ('screen.availWidth', aw),
                       ('screen.availHeight', ah), ('window.outerWidth', ow), ('window.outerHeight', oh),
                       ('window.innerWidth', iw), ('window.innerHeight', ih), ('window.screenX', sx),
                       ('window.screenY', sy)):
        v = maybe(rng, value, p_none=p_none)
        if v != '__missing__':
            c[key] = v
    return c


UAS = [
    'Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Mozilla/5.0 (X11; Linux i686; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0',
    'Mozilla/5.0 (Android 16; Mobile; rv:152.0) Gecko/152.0 Firefox/152.0',
    'Mozilla/5.0 (X11; Linux aarch64; rv:152.0) Gecko/20100101 Firefox/152.0',
    '',
]
PLATFORMS = ['Linux x86_64', 'Linux armv81', 'Linux i686', 'Win32', 'MacIntel', 'Linux aarch64', '']


def record_geometry():
    rng = random.Random(4242)
    cases = []
    for i in range(500):
        c = random_geometry(rng)
        target = OS_KEYS[i % 3]
        cap_w = rng.choice([None, 1366, 1920, 1280, 2560, 0])
        cap_h = rng.choice([None, 768, 1080, 720, 1440, 0])
        out = {}
        for name, fn in (
            ('fixScreenNoTaskbar', lambda d: fp.fix_screen_no_taskbar(d, target)),
            ('clampWindowDimensions', fp.clamp_window_dimensions),
            ('clampScreenToDisplay', lambda d: fp.clamp_screen_to_display(d, cap_w, cap_h)),
            ('clampWindowPosition', fp.clamp_window_position),
            ('raiseScreenToModernFloor', fp.raise_screen_to_modern_floor),
            ('repairScreenOrientation', coherence.repair_screen_orientation),
        ):
            d = copy.deepcopy(c)
            ret = fn(d)
            out[name] = {'config': d, 'ret': ret} if i < 15 else {'hash': h(d), 'keys': h(list(d)), 'ret': ret}

        # the launch_options order
        d = copy.deepcopy(c)
        if coherence.screen_is_implausible(d):
            coherence.repair_screen_orientation(d)
            fp.raise_screen_to_modern_floor(d)
        fp.raise_screen_to_modern_floor(d)
        fp.clamp_screen_to_display(d, cap_w, cap_h)
        fp.fix_screen_no_taskbar(d, target)
        fp.clamp_window_dimensions(d)
        fp.clamp_window_position(d)
        out['pipeline'] = {'config': d} if i < 15 else {'hash': h(d), 'keys': h(list(d))}
        cases.append({'input': c, 'os': target, 'capW': cap_w, 'capH': cap_h, 'out': out})

    arch = []
    for ua in UAS:
        for plat in PLATFORMS + [None]:
            for oscpu in ('Linux armv81', 'Linux x86_64', None):
                for target in OS_KEYS:
                    c = {'navigator.userAgent': ua}
                    if plat is not None:
                        c['navigator.platform'] = plat
                    if oscpu is not None:
                        c['navigator.oscpu'] = oscpu
                    d = copy.deepcopy(c)
                    fp.fix_navigator_arch(d, target)
                    arch.append([ua, plat, oscpu, target, d.get('navigator.platform'), d.get('navigator.oscpu')])

    hc = []
    for host in (None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 22, 24, 26, 32, 64, 128):
        for supported in (True, False):
            for can_pin in (None, True, False):
                for drawn in (None, 1, 2, 3, 4, 5, 7, 8, 9, 11, 13, 15, 16, 18, 24, 32, 48, True, '8', 8.5):
                    c = {} if drawn is None else {'navigator.hardwareConcurrency': drawn}
                    d = copy.deepcopy(c)
                    with mock.patch.object(fp, 'host_cpu_count', lambda n=host: n), \
                            mock.patch.object(cpu_affinity, 'supported', lambda s=supported: s):
                        fp.fix_hardware_concurrency(d, can_pin=can_pin)
                    hc.append([drawn, host, supported, can_pin, d.get('navigator.hardwareConcurrency', '__missing__')])
    write('geometry.json', {'cases': cases, 'arch': arch, 'hardwareConcurrency': hc})


def fpgen_renderers():
    """Every renderer fpgen records from Firefox, once each, in trace order."""
    renderers = [r.value['renderer'] for os_key in OS_KEYS for r in webgl._trace('gpu', os_key)]
    return list(dict.fromkeys(renderers))


EXTRA_RENDERERS = [
    'ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar',
    'NVIDIA GeForce GTX 980/PCIe/SSE2', 'GeForce GTX 980, or similar',
    'ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar',
    'Radeon HD 3200 Graphics, or similar', 'ANGLE (Samsung Xclipse 920) on Vulkan',
    'ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar', 'Apple M1, or similar',
    'llvmpipe, or similar', 'ANGLE (Microsoft, Microsoft Basic Render Driver Direct3D11 vs_5_0 ps_5_0)',
    'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)', 'Generic Renderer',
    'ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)', 'Intel(R) HD Graphics 400, or similar',
    'Radeon R9 200 Series, or similar', 'NVIDIA GeForce GTX 480/PCI/SSE2', 'GeForce 8800 GTX', '', 'Mozilla',
]


def record_coherence():
    renderers = fpgen_renderers() + EXTRA_RENDERERS
    rng = random.Random(9001)
    fits = [[r, os_key, coherence.gpu_fits_os(r, os_key)] for r in renderers + [None] for os_key in OS_KEYS + ('bsd',)]
    machine = [[r, os_key, cores, w, hh, coherence.gpu_fits_machine(r, os_key, cores, w, hh)]
               for r in renderers + [None] for os_key in OS_KEYS + ('bsd',)
               for cores in (None, 2, 8, 10, 20, 22, 56, True, '8')
               for w, hh in ((1470, 956), (2056, 1329), (1920, 1080), ('1470', 956), (None, None))]
    gpu = []
    for r in renderers + [None]:
        for w, hh in ((1024, 600), (800, 480), (1024, 768), (1366, 768), (1920, 1080), (None, None), (0, 600)):
            gpu.append([r, w, hh, fp.gpu_screen_is_plausible(r, w, hh), fp.is_software_renderer(r),
                        fp._renderer_bucket(r) if r is not None else None])

    cases = []
    for i in range(900):
        c = random_geometry(rng, p_none=0) if rng.random() < 0.7 else {}
        fields = {
            'webGl:renderer': rng.choice(renderers + [None]),
            'navigator.hardwareConcurrency': rng.choice([2, 4, 6, 8, 9, 10, 11, 12, 13, 16, 24, 33, 64, True, '8']),
            'screen.colorDepth': rng.choice([24, 30, 32, 16, 48, True, '24']),
            'navigator.maxTouchPoints': rng.choice([0, 1, 2, 5, 10, 11, 40, 256, -1, 1.5, True, '5']),
            'window.devicePixelRatio': rng.choice([1, 1.25, 1.5, 1.75, 2, 2.5, 3, 1.125, 1.1, 1.818181818181818,
                                                   1.09, 3.5, 0.9, 2.25, 1.625, 2.75, '2']),
            'screen.pixelDepth': rng.choice([24, 30, 32]),
            'navigator.userAgent': rng.choice(UAS),
            'navigator.platform': rng.choice(PLATFORMS),
            'navigator.oscpu': rng.choice(PLATFORMS),
        }
        for key, value in fields.items():
            if rng.random() < 0.6:
                c[key] = value
        if rng.random() < 0.2:
            c['screen.width'], c['screen.height'] = rng.choice(sorted(coherence.APPLE_SILICON_PANELS))
        target = rng.choice(OS_KEYS + ('bsd',))
        v = [list(x) for x in coherence.validate(c, target)]
        applied = copy.deepcopy(c)
        left = [list(x) for x in coherence.apply(applied, target)]
        dropped_cfg = copy.deepcopy(c)
        dropped = [list(x) for x in coherence.drop_incoherent_source_values(dropped_cfg, target)]
        case = {'input': c, 'os': target, 'rules': [x[0] for x in v], 'validate': h(v),
                'apply': [x[0] for x in left], 'applyHash': h(left), 'applied': h(applied),
                'dropped': dropped, 'droppedConfig': h(dropped_cfg),
                'implausible': coherence.screen_is_implausible(c)}
        if i < 40:
            case.update(validateFull=v, appliedFull=applied)
        cases.append(case)
    write('coherence.json', {'fits': fits, 'machine': machine, 'gpuScreen': gpu, 'cases': cases})


# ---------------------------------------------------------------------------
# fpgen -> config, presets
# ---------------------------------------------------------------------------


def trimmed(f):
    return {k: f[k] for k in ('navigator', 'screen', 'window', 'headers') if k in f}


def record_from_fpgen_inputs():
    """from_fpgen goldens over stored inputs (generated once, trimmed)."""
    inputs = []
    for os_name in OS_NAMES:
        for _ in range(25):
            inputs.append(trimmed(fp.generate_fingerprint(os=os_name)))
    # Hand-made edge cases: windowed screenX, negatives, header lists, empties.
    inputs.append({'navigator': {'userAgent': 'Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0',
                                 'platform': 'Linux x86_64', 'hardwareConcurrency': 0, 'maxTouchPoints': 0,
                                 'oscpu': ''},
                   'screen': {'width': 1920, 'height': 1080, 'availHeight': 1040, 'availLeft': -5, 'availTop': 0},
                   'window': {'screenX': 300, 'outerHeight': 900, 'outerWidth': 1200},
                   'headers': {'accept-encoding': ['gzip, deflate, br', 'gzip'], 'accept-language': ['en']}})
    inputs.append({'screen': {'availHeight': 700}, 'window': {'screenX': -120, 'outerHeight': 900},
                   'headers': {'accept-encoding': ['gzip, deflate, br, zstd']}})
    inputs.append({'window': {'screenX': 51}, 'screen': {}})
    inputs.append({'window': {'screenX': 50, 'screenY': 3}})
    inputs.append({'navigator': {'userAgent': 'Firefox/115.0 rv:115.0 1115.0 115.01 Firefox/99.0'}})
    inputs.append({})
    cases = []
    for i, f in enumerate(inputs):
        for ffv in (None, '152'):
            random.seed(1000 + i)
            config = fp.from_fpgen(copy.deepcopy(f), ffv)
            cases.append({'input': i, 'ffVersion': ffv, 'moduleSeed': 1000 + i, 'config': config,
                          'configKeys': list(config.keys()),
                          'identitySeed': fp.identity_seed(config, 12345678901234567890)})
    windows = []
    for i, f in enumerate(inputs[:20]):
        for w, hh in ((1280, 720), (800, 600), (1920, 1080)):
            d = copy.deepcopy(f)
            fp.handle_window_size(d, w, hh)
            windows.append({'input': i, 'w': w, 'h': hh, 'out': d})
    screens = []
    for bounds in ((None, None, None, None), (100, 2000, None, None), (None, 1920, None, 1080), (1366, 1366, 768, 768)):
        s = fp.Screen(*bounds)
        conds = s.as_conditions()
        probes = [800, 1366, 1920, 2560, 1080.0, '1920', None]
        screens.append({'bounds': list(bounds), 'keys': sorted(conds),
                        'width': [conds['screen.width'](p) for p in probes] if 'screen.width' in conds else None,
                        'height': [conds['screen.height'](p) for p in probes] if 'screen.height' in conds else None})
    write('from-fpgen.json', {'inputs': inputs, 'cases': cases, 'windowSize': windows, 'screens': screens})


def record_presets():
    base = Path(fp.__file__).parent
    cases = []
    full = []
    for fname, ffv in (('fingerprint-presets.json', None), ('fingerprint-presets-v150.json', '152')):
        presets = json.loads((base / fname).read_text())['presets']
        for os_name, entries in presets.items():
            for i, preset in enumerate(entries):
                for salt in (0, 12345678901234567890):
                    random.seed(i * 7 + salt % 1000)
                    config = fp.from_preset(copy.deepcopy(preset), ffv, salt=salt)
                    key = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}[os_name]
                    cases.append({'file': fname, 'os': os_name, 'index': i, 'ffVersion': ffv, 'salt': str(salt),
                                  'moduleSeed': i * 7 + salt % 1000, 'hash': h(config),
                                  'keys': h(list(config.keys())),
                                  'validate': [x.rule for x in coherence.validate(config, key)]})
                    if i < 2 and salt == 0:
                        full.append({'file': fname, 'os': os_name, 'index': i, 'config': hashed_lists(config)})
    # Synthetic presets: derived oscpu / appVersion, fallbacks.
    synthetic = [
        {'navigator': {'platform': 'Linux x86_64', 'userAgent': UAS[0]}},
        {'navigator': {'platform': 'Win32', 'userAgent': UAS[3], 'appVersion': '5.0 (Windows NT 10.0; Win64; x64)'}},
        {'navigator': {'platform': 'iPhone', 'userAgent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Gecko/20100101'}},
        {'navigator': {'platform': 'Win32', 'userAgent': 'not a user agent', 'maxTouchPoints': 0}},
        {'navigator': {'platform': 'MacIntel', 'hardwareConcurrency': 0}, 'screen': {'width': 1440, 'colorDepth': 30},
         'webgl': {'unmaskedVendor': 'Apple', 'unmaskedRenderer': 'Apple M1, or similar'}, 'timezone': 'Europe/Paris'},
        {},
    ]
    synth = []
    for i, preset in enumerate(synthetic):
        for ffv in (None, '152'):
            random.seed(5000 + i)
            config = fp.from_preset(copy.deepcopy(preset), ffv, salt=99)
            synth.append({'preset': preset, 'ffVersion': ffv, 'moduleSeed': 5000 + i, 'config': hashed_lists(config)})
    rand = []
    for os_arg in (None, 'windows', 'mac', 'lin', ['linux', 'macos'], 'bsd'):
        for ffv in (None, '152', '148', 'abc'):
            for seed in range(10):
                random.seed(seed)
                preset = fp.get_random_preset(os=os_arg, ff_version=ffv)
                rand.append({'os': os_arg, 'ffVersion': ffv, 'moduleSeed': seed,
                             'hash': None if preset is None else h(preset)})
    app_versions = []
    uas = set(UAS)
    for fname in ('fingerprint-presets.json', 'fingerprint-presets-v150.json'):
        for entries in json.loads((base / fname).read_text())['presets'].values():
            for preset in entries:
                ua = (preset.get('navigator') or {}).get('userAgent')
                if ua:
                    uas.add(ua)
    uas |= {'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:52.0) Gecko/20100101 Firefox/52.0',
            'Mozilla/5.0 (X11; Linux x86_64)', 'Mozilla/5.0 (rv:1.0)', 'Mozilla/5.0 ()', None}
    for ua in sorted(uas, key=lambda x: x or ''):
        app_versions.append([ua, fp._app_version_from_user_agent(ua)])
    write('presets.json', {'cases': cases, 'full': full, 'synthetic': synth, 'random': rand,
                           'appVersions': app_versions,
                           'presetsFile': {str(v): Path(fp._select_presets_file(v)).name
                                           for v in (None, '148', '149', '150.0.2', 'abc', 152, '', ' 150')}})


def record_constants():
    write('constants.json', compress=False, data={
        'fpgenData': fp.FPGEN_DATA,
        'essentialMacos': fp._ESSENTIAL_FONTS_MACOS,
        'essentialWindows': fp._ESSENTIAL_FONTS_WINDOWS,
        'essentialLinux': fp._ESSENTIAL_FONTS_LINUX,
        'markers': {'macos': fp._MACOS_MARKER_FONTS, 'windows': fp._WINDOWS_MARKER_FONTS,
                    'linux': fp._LINUX_MARKER_FONTS},
        'windows11Markers': sorted(fp.WINDOWS_11_MARKER_FONTS),
        'plausibleCoreCounts': list(fp.PLAUSIBLE_CORE_COUNTS),
        'modernScreenFloor': list(fp.MODERN_SCREEN_FLOOR),
        'appleSiliconCores': sorted(coherence.APPLE_SILICON_CORES),
        'intelMacIgpCores': sorted(coherence.INTEL_MAC_IGP_CORES),
        'intelMacDgpuCores': sorted(coherence.INTEL_MAC_DGPU_CORES),
        'appleSiliconPanels': sorted(f'{w}x{hh}' for w, hh in coherence.APPLE_SILICON_PANELS),
        'plausibleDpr': {k: list(v) for k, v in coherence.PLAUSIBLE_DPR.items()},
        'plausibleColorDepth': sorted(coherence.PLAUSIBLE_COLOR_DEPTH),
        'maxTouchPoints': coherence.MAX_PLAUSIBLE_TOUCH_POINTS,
        'browserChromeHeight': coherence.BROWSER_CHROME_HEIGHT,
        'rules': [r.name for r in coherence.RULES],
        'macNovelty': sorted(fp._MAC_NOVELTY_VOICES),
        'macEloquence': sorted(fp._MAC_ELOQUENCE_VOICES),
        'presetsV150MinFf': fp.PRESETS_V150_MIN_FF,
    })


def record_init_script():
    cases = [
        {},
        {'audioFingerprintSeed': 123,
         'navigatorPlatform': 'Win32', 'navigatorOscpu': 'Windows NT 10.0; Win64; x64',
         'navigatorUserAgent': UAS[3], 'hardwareConcurrency': 8, 'webglVendor': 'Google Inc. (Intel)',
         'webglRenderer': 'ANGLE (Intel, "quoted" é)', 'screenWidth': 1920, 'screenHeight': 1080,
         'screenColorDepth': 24, 'timezone': 'Europe/Paris', 'fontList': ['Arial', '微软雅黑', 'Segoe UI'],
         'speechVoices': [{'name': 'Microsoft David'}, 'Plain Name'], 'webrtcIP': '1.2.3.4'},
        {'screenWidth': 1920, 'screenHeight': None, 'screenColorDepth': 24, 'webrtcIP': '', 'fontList': [],
         'speechVoices': [], 'timezone': ''},
        {'navigatorUserAgent': 'emoji 😀   \x7f tab\t', 'hardwareConcurrency': None},
        {'webrtcIP': '2001:db8::7'},
    ]
    out = [{'values': v, 'script': fp._build_init_script(v)} for v in cases]
    write('init-script.json', {'cases': out}, compress=False)


def main():
    record_constants()
    record_pyrandom()
    record_numpy()
    record_pycompat()
    record_fpgen_salts()
    record_fonts()
    record_voices()
    record_media()
    record_webgl()
    record_geometry()
    record_coherence()
    record_from_fpgen_inputs()
    record_presets()
    record_init_script()


if __name__ == '__main__':
    main()
