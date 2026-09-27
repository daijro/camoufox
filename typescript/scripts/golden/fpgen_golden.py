#!/usr/bin/env python3
"""Golden fixtures for the TypeScript fpgen port (typescript/src/fpgen/).

Run from the repo root with the worktree venv, which has fpgen and the PINNED
model installed (scripts/pin-fpgen-model.py):

    .venv/bin/python typescript/scripts/golden/fpgen_golden.py

Writes typescript/tests/fixtures/fpgen/*.json. Everything except stats.json is
deterministic -- network structure, value lookups, beam-search distributions,
condition -> evidence, query() -- and the TS tests compare against it exactly.
stats.json holds marginal counts from real Python draws; the TS test compares
its own draws against them statistically, because Python samples with
`random.random()` and cannot be matched draw-for-draw.

The CASES tables below are mirrored by name in typescript/tests/fpgen*.test.ts;
predicates are named because a lambda cannot be serialised.
"""

import hashlib
import json
import os
import random
import re
import struct
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
TS_ROOT = HERE.parent.parent
REPO = TS_ROOT.parent
OUT = TS_ROOT / 'tests' / 'fixtures' / 'fpgen'
PIN = json.loads((REPO / 'scripts' / 'data' / 'fpgen-model.json').read_text())

STATS_N = int(os.environ.get('FPGEN_GOLDEN_STATS_N', '3000'))


def _guard_model():
    """Refuse to run against anything but the pinned model, and keep fpgen from
    'refreshing' it: fpgen re-downloads (unverified, wrong release) when its
    files look older than five weeks, so bump their mtime before importing."""
    import importlib.util

    spec = importlib.util.find_spec('fpgen')
    if spec is None or not spec.origin:
        sys.exit('fpgen is not installed in this interpreter')
    data = Path(spec.origin).parent / 'data'
    stamp = data / '.pinned-model'
    if not stamp.exists() or stamp.read_text().strip() != PIN['sha256']:
        sys.exit(f'fpgen model in {data} is not pinned to {PIN["tag"]}; '
                 'run scripts/pin-fpgen-model.py first')
    now = time.time()
    for f in PIN['files']:
        os.utime(data / f, (now, now))


_guard_model()

import fpgen  # noqa: E402
import fpgen.bayesian_network as bn  # noqa: E402
from fpgen import Generator, query, trace  # noqa: E402
from fpgen.unpacker import VALUE_PAIRS, base85_to_int, lookup_value_list  # noqa: E402
from fpgen.utils import NETWORK, build_evidence  # noqa: E402

# Count beam prunings so the fixture can prove the exact-match traces cover them.
_PRUNES = [0]
_nlargest = bn.heapq.nlargest


def _counting_nlargest(*a, **k):
    _PRUNES[0] += 1
    return _nlargest(*a, **k)


bn.heapq.nlargest = _counting_nlargest

# Predicates, by name. The TS test defines the same names.
PREDICATES = {
    'screen_width_1280_1920': lambda w: isinstance(w, int) and 1280 <= w <= 1920,
    'os_linux_or_windows': lambda v: v in {'linux', 'windows'},
    'hc_at_least_8': lambda v: isinstance(v, int) and v >= 8,
    'ua_rv146': lambda v: 'rv:146' in v,
    'never': lambda v: False,
}


class Pred:
    def __init__(self, name):
        self.name = name


class Alt:
    """A tuple of alternatives (a Set in TS)."""

    def __init__(self, *values):
        self.values = values


def to_py(cond):
    if isinstance(cond, Pred):
        return PREDICATES[cond.name]
    if isinstance(cond, Alt):
        return tuple(to_py(v) for v in cond.values)
    if isinstance(cond, dict):
        return {k: to_py(v) for k, v in cond.items()}
    return cond


def to_fixture(cond):
    if isinstance(cond, Pred):
        return {'$pred': cond.name}
    if isinstance(cond, Alt):
        return {'$alt': [to_fixture(v) for v in cond.values]}
    if isinstance(cond, dict):
        return {k: to_fixture(v) for k, v in cond.items()}
    return cond


def chrome_ua():
    uas = query('navigator.userAgent')
    return next(u for u in uas if 'Chrome/' in u and 'Firefox' not in u)


CONDITION_CASES = [
    ('empty', {}),
    ('firefox', {'browser': 'Firefox'}),
    ('firefox_windows', {'browser': 'Firefox', 'os': 'Windows'}),
    ('firefox_linux', {'browser': 'Firefox', 'os': 'Linux'}),
    ('firefox_macos', {'browser': 'Firefox', 'os': 'macOS'}),
    ('casefolded_keys_values', {'Browser': 'firefox', 'OS': 'WINDOWS'}),
    ('nested_dict', {'browser': 'Firefox', 'screen': {'width': 1920, 'height': 1080}}),
    ('dotted_key', {'browser': 'Firefox', 'screen.width': 2560}),
    ('alt_os', {'browser': 'Firefox', 'os': Alt('Linux', 'Windows')}),
    ('alt_nested', {'browser': 'Firefox', 'screen.width': Alt(1920, 2560)}),
    ('pred_screen', {'browser': 'Firefox', 'os': 'Windows',
                     'screen.width': Pred('screen_width_1280_1920')}),
    ('pred_os', {'browser': 'Firefox', 'os': Pred('os_linux_or_windows')}),
    ('pred_hc', {'browser': 'Firefox', 'navigator.hardwareConcurrency': Pred('hc_at_least_8')}),
    ('pred_ua', {'navigator.userAgent': Pred('ua_rv146')}),
    ('list_value', {'navigator.languages': ['en-US', 'en']}),
    ('nested_string', {'browser': 'Firefox', 'gpu': {'vendor': 'Apple'}}),
    ('device_memory', {'navigator.deviceMemory': 8}),
    ('hc_int', {'browser': 'Firefox', 'os': 'Linux', 'navigator.hardwareConcurrency': 16}),
]

ERROR_CASES = [
    ('bad_value', {'os': 'Plan9'}, True),
    ('bad_node', {'nosuch.node': 1}, True),
    ('bad_root_node', {'nosuch': 1}, True),
    ('empty_key', {'': 1}, True),
    ('bad_nested_value', {'screen.width': 12345}, True),
    ('bad_nested_path', {'screen.nosuchfield': 1}, True),
    ('pred_never', {'os': Pred('never')}, True),
    ('pred_never_nested', {'screen.width': Pred('never')}, True),
    ('restrictive', {'browser': 'Firefox', 'navigator.userAgent': '$CHROME_UA'}, True),
    # Not strict: fpgen drops the FIRST key and does not re-validate.
    ('restrictive_relaxed', {'browser': 'Firefox', 'navigator.userAgent': '$CHROME_UA'}, False),
]

TRACE_TARGETS = [
    'os', 'navigator.userAgent', 'screen', 'navigator.hardwareConcurrency', 'gpu', 'gpuInfo',
]
# Deep nodes with big supports, traced for a few cases only to keep the fixture small.
EXTRA_TRACE_TARGETS = ['allFonts', 'window']
EXTRA_TRACE_CASES = {'empty', 'firefox_linux', 'list_value', 'pred_hc'}


def subst(cond, ua):
    if cond == '$CHROME_UA':
        return ua
    if isinstance(cond, dict):
        return {k: subst(v, ua) for k, v in cond.items()}
    return cond


def evidence_fixture(evidence):
    return [[k, sorted(v, key=base85_to_int)] for k, v in evidence.items()]


def dist_fixture(dist):
    return [[k, p] for k, p in dist.items()]


def float_hex(x):
    return struct.pack('>d', float(x)).hex()


def cpt_canonical(o):
    if isinstance(o, dict):
        return '{' + ','.join(json.dumps(k) + ':' + cpt_canonical(v) for k, v in o.items()) + '}'
    return float_hex(o)


def sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def write(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False) + '\n')
    print(f'{path.relative_to(REPO)}: {path.stat().st_size} bytes', file=sys.stderr)


def all_ids():
    ids = set()
    for node in NETWORK.nodes_in_sampling_order:
        ids.update(node.possible_values)
    return sorted(ids, key=base85_to_int)


def gen_structure():
    nodes = []
    for node in NETWORK.nodes_in_sampling_order:
        nodes.append({
            'name': node.name,
            'parentNames': node.parent_names,
            'possibleValues': node.possible_values,
            'cptSha256': sha(cpt_canonical(node.probabilities)),
            'ancestors': sorted(NETWORK.get_all_ancestors(node.name)),
        })
    ids = all_ids()
    return {
        'pin': PIN['sha256'],
        'fpgenVersion': '1.3.0',
        'nodeNames': list(NETWORK.node_names),
        'nodes': nodes,
        'valuePairs': {
            'count': len(VALUE_PAIRS),
            'sha256': sha(''.join(f'{int(o, 16)}:{n};' for o, n in VALUE_PAIRS)),
        },
        'base85': {
            'count': len(ids),
            'sha256': sha(''.join(f'{i}={base85_to_int(i)};' for i in ids)),
            'samples': {i: base85_to_int(i) for i in ids[:: max(1, len(ids) // 200)]},
        },
    }


def gen_values():
    ids = all_ids()
    rng = random.Random(1234)
    sample = sorted(rng.sample(ids, 300), key=base85_to_int)
    texts = lookup_value_list(sample)
    samples = []
    for i, t in zip(sample, texts):
        entry = {'id': i, 'length': len(t.encode()), 'sha256': sha(t)}
        if len(t) <= 160:
            entry['text'] = t
        samples.append(entry)
    # Digest of every referenced value, in id order, in chunks.
    h = hashlib.sha256()
    for n in range(0, len(ids), 500):
        for t in lookup_value_list(ids[n:n + 500]):
            h.update(sha(t).encode())
    return {'samples': samples, 'allIdsDigest': h.hexdigest(), 'idCount': len(ids)}


def gen_conditions(ua):
    out = []
    for name, cond in CONDITION_CASES:
        evidence = {}
        build_evidence(to_py(cond), evidence)
        traces = {}
        before = _PRUNES[0]
        targets = TRACE_TARGETS + (EXTRA_TRACE_TARGETS if name in EXTRA_TRACE_CASES else [])
        for target in targets:
            traces[target] = dist_fixture(NETWORK.trace(target, evidence))
        out.append({
            'name': name,
            'conditions': to_fixture(cond),
            'evidence': evidence_fixture(evidence),
            'traces': traces,
            'pruned': _PRUNES[0] - before,
        })
    errors = []
    for name, cond, strict in ERROR_CASES:
        cond = subst(cond, ua)
        evidence = {}
        entry = {'name': name, 'conditions': to_fixture(cond), 'strict': strict}
        try:
            build_evidence(to_py(cond), evidence, strict=strict)
            entry['evidence'] = evidence_fixture(evidence)
        except Exception as exc:  # noqa: BLE001 -- recording the class is the point
            entry['error'] = type(exc).__name__
            entry['message'] = str(exc)
        errors.append(entry)
    return {'cases': out, 'errors': errors}


def trace_results(res):
    if isinstance(res, list):
        return [{'value': r.value, 'probability': r.probability} for r in res]
    return {k: trace_results(v) for k, v in res.items()}


def gen_api():
    """Public-API outputs: trace(), Generator.trace, query(), deterministic generate()."""
    traces = []
    for name, target, cond, kw in [
        ('os_firefox', 'os', {'browser': 'Firefox'}, {}),
        ('hc_firefox_linux', 'navigator.hardwareConcurrency',
         {'browser': 'Firefox', 'os': 'Linux'}, {}),
        ('screen_firefox_macos', 'screen', {'browser': 'Firefox', 'os': 'macOS'}, {}),
        ('inside_node', 'screen.width', {'browser': 'Firefox', 'os': 'Linux'}, {}),
        ('two_targets_nested', ['navigator.platform', 'navigator.oscpu'], {'browser': 'Firefox'}, {}),
        ('two_targets_flat', ['navigator.platform', 'navigator.oscpu'], {'browser': 'Firefox'},
         {'flatten': True}),
        ('prefix_target', 'headers.sec-fetch', {'browser': 'Firefox'}, {}),
        ('pred', 'os', {'browser': 'Firefox', 'os': Pred('os_linux_or_windows')}, {}),
    ]:
        traces.append({
            'name': name, 'target': target, 'conditions': to_fixture(cond), 'options': kw,
            'result': trace_results(trace(target, to_py(cond), **kw)),
        })
    gen_trace = trace_results(Generator(browser='Firefox', os='Windows').trace('navigator.platform'))

    queries = []
    for target, kw in [
        ('os', {}), ('os', {'sort': True}),
        ('navigator.hardwareConcurrency', {}), ('navigator.hardwareConcurrency', {'sort': True}),
        ('navigator.deviceMemory', {'sort': True}),
        ('screen', {'sort': True}), ('screen', {'sort': True, 'flatten': True}),
        ('screen.width', {'sort': True}),
        ('window', {'sort': True}),
        ('windowComponents', {}),
        ('navigator', {'sort': True}), ('navigator', {'sort': True, 'flatten': True}),
        ('matchmedia', {'sort': True}),
        ('headers', {'sort': True, 'flatten': True}),
        ('permissions.geolocation', {}),
        # The only node whose merged lists mix ints and integral floats (grouping by type).
        ('audio.values', {'sort': True}),
    ]:
        queries.append({'target': target, 'options': kw, 'result': query(target, **kw)})
    query_errors = []
    for target in ['nosuch', 'screen.nosuchfield', 'navigator.nosuch', 'matchMedia']:
        try:
            query(target)
            query_errors.append({'target': target, 'error': None})
        except Exception as exc:  # noqa: BLE001
            query_errors.append({'target': target, 'error': type(exc).__name__, 'message': str(exc)})

    # generate() outputs that do not depend on the draw (checked by repetition).
    deterministic = []
    for name, cond, kw in [
        ('appName', {'browser': 'Firefox'}, {'target': 'navigator.appName'}),
        ('two', {'browser': 'Firefox'}, {'target': ['navigator.appCodeName', 'navigator.productSub']}),
        ('platform_win', {'browser': 'Firefox', 'os': 'Windows'}, {'target': 'navigator.platform'}),
        ('platform_mac', {'browser': 'Firefox', 'os': 'macOS'}, {'target': 'navigator.platform'}),
        ('casefold_target', {'browser': 'Firefox', 'os': 'Windows'}, {'target': 'NAVIGATOR.PLATFORM'}),
        ('flat_target', {'browser': 'Firefox', 'os': 'Windows'},
         {'target': ['navigator.appName', 'navigator.platform'], 'flatten': True}),
    ]:
        outs = [Generator().generate(to_py(cond), **kw) for _ in range(20)]
        if any(o != outs[0] for o in outs):
            sys.exit(f'deterministic case {name} is not deterministic')
        deterministic.append({'name': name, 'conditions': cond, 'options': kw, 'result': outs[0]})

    g = Generator(browser='Firefox')
    shapes = {
        'topLevelKeys': sorted(g.generate().keys()),
        'navigatorKeys': sorted(g.generate(target='navigator').keys()),
        'flatKeysSample': sorted(k for k in g.generate(flatten=True) if k.startswith('navigator.')),
    }
    return {'traces': traces, 'generatorTrace': gen_trace, 'queries': queries,
            'queryErrors': query_errors, 'deterministic': deterministic, 'shapes': shapes}


# ---- statistics -----------------------------------------------------------

STATS_SCENARIOS = [
    ('firefox_any', {'browser': 'Firefox'}),
    ('firefox_windows', {'browser': 'Firefox', 'os': 'Windows'}),
    ('firefox_linux', {'browser': 'Firefox', 'os': 'Linux'}),
    ('firefox_macos', {'browser': 'Firefox', 'os': 'macOS'}),
    ('firefox_windows_screen_bound', {'browser': 'Firefox', 'os': 'Windows',
                                      'screen.width': Pred('screen_width_1280_1920')}),
]


def fields(fp):
    """The marginals compared. Mirrored by fields() in fpgen-stats.test.ts."""
    ua = fp['navigator']['userAgent']
    m = re.search(r'\(([^)]*)\)', ua)
    platform = m.group(1).split('; rv:')[0] if m else ''
    rv = re.search(r'rv:(\d+)', ua)
    return {
        'os': fp['os'],
        'uaPlatform': platform,
        'firefoxMajor': rv.group(1) if rv else '',
        'screen': f"{fp['screen']['width']}x{fp['screen']['height']}",
        'hardwareConcurrency': str(fp['navigator']['hardwareConcurrency']),
        'gpuVendor': fp['gpu']['vendor'],
    }


_WORKER_GEN = None


def _draw(args):
    global _WORKER_GEN
    scenario, n, seed = args
    random.seed(seed)
    if _WORKER_GEN is None:
        _WORKER_GEN = Generator()
    cond = to_py(dict(STATS_SCENARIOS)[scenario])
    counts = {}
    for _ in range(n):
        for k, v in fields(_WORKER_GEN.generate(cond)).items():
            counts.setdefault(k, Counter())[v] += 1
    return scenario, counts


def gen_stats():
    chunk = 100
    jobs = []
    for s, (name, _) in enumerate(STATS_SCENARIOS):
        for c in range(STATS_N // chunk):
            jobs.append((name, chunk, s * 100000 + c))
    merged = {name: {} for name, _ in STATS_SCENARIOS}
    with Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        for scenario, counts in pool.imap_unordered(_draw, jobs):
            for k, c in counts.items():
                merged[scenario].setdefault(k, Counter()).update(c)
    return {
        'n': STATS_N,
        'scenarios': [
            {'name': name, 'conditions': to_fixture(cond),
             'counts': {k: dict(sorted(v.items())) for k, v in merged[name].items()}}
            for name, cond in STATS_SCENARIOS
        ],
    }


def main():
    only = set(sys.argv[1:])

    def want(x):
        return not only or x in only

    t = time.time()
    if want('structure'):
        write('structure.json', gen_structure())
    if want('values'):
        write('values.json', gen_values())
    if want('conditions'):
        write('conditions.json', gen_conditions(chrome_ua()))
    if want('api'):
        write('api.json', gen_api())
    if want('stats'):
        write('stats.json', gen_stats())
    print(f'done in {time.time() - t:.1f}s (fpgen {fpgen.__name__})', file=sys.stderr)


if __name__ == '__main__':
    main()
