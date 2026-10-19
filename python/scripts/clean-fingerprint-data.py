#!/usr/bin/env python3
"""Drop identities the shipped data files cannot honestly offer.

`camoufox.coherence` checks an identity when one is drawn. This does the same
to the DATA the identities are drawn FROM, so an impossible row never reaches a
build in the first place. Two filters for the same rules: the runtime one has to
produce an identity and so repairs what it can, while this one can simply drop a
row -- there are plenty of others, and dropping loses nothing but a machine that
never existed.

What it covers:

  fingerprint-presets.json, fingerprint-presets-v150.json
      Each preset is converted the way a launch converts it and checked, and
      its GPU must be one fpgen has seen Firefox report on that OS: WebGL
      parameters come from fpgen, and a GPU it has never seen has none. A row
      that fails is dropped rather than repaired: repairing would write an
      invented value ("what core count does a 2-core Apple M1 really have?")
      into a file whose entire purpose is being real.

Usage:
    python3 python/scripts/clean-fingerprint-data.py            # report only
    python3 python/scripts/clean-fingerprint-data.py --write    # rewrite the files

`--check` exits non-zero when anything would be dropped;
python/tests/test_shipped_data.py asserts the same thing, so a data refresh that
reintroduces a bad row fails CI rather than shipping.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PYTHON_SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(PYTHON_SRC))

from camoufox import coherence  # noqa: E402
from camoufox.fingerprints import from_preset  # noqa: E402
from camoufox.webgl import firefox_gpus  # noqa: E402

PRESET_FILES = (
    PYTHON_SRC / 'camoufox' / 'fingerprint-presets.json',
    PYTHON_SRC / 'camoufox' / 'fingerprint-presets-v150.json',
)
OS_KEY = {'macos': 'mac', 'windows': 'win', 'linux': 'lin'}
# The Firefox version only decides the UA rewrite, which no rule reads.
FF_VERSION = '152'


def preset_violations(preset, os_name):
    """What this preset breaks, as a launch would see it."""
    try:
        config = from_preset(preset, FF_VERSION)
    except Exception as exc:  # a row too malformed to convert is itself a defect
        return [coherence.Violation('unconvertible', f'{type(exc).__name__}: {exc}')]
    violations = coherence.validate(config, OS_KEY[os_name])
    gpu = (preset.get('webgl', {}).get('unmaskedVendor'), preset.get('webgl', {}).get('unmaskedRenderer'))
    if gpu not in firefox_gpus(os_name):
        violations.append(coherence.Violation(
            'gpu-without-webgl-data', f'fpgen has never seen Firefox on {os_name} report {gpu[1]!r}'))
    return violations


def clean_presets(path, write):
    data = json.loads(path.read_text())
    dropped = Counter()
    kept_total = dropped_total = 0
    for os_name, presets in data['presets'].items():
        kept = []
        for index, preset in enumerate(presets):
            violations = preset_violations(preset, os_name)
            if violations:
                dropped_total += 1
                for violation in violations:
                    dropped[violation.rule] += 1
                print(f'  drop {path.name} {os_name}[{index}]: '
                      f'{"; ".join(v.detail for v in violations)[:120]}')
            else:
                kept.append(preset)
        kept_total += len(kept)
        data['presets'][os_name] = kept
    if write and dropped_total:
        # Keep the file's own formatting. Rewriting 2-space-indented JSON
        # compactly turns a 38-row deletion into a 22,546-line diff that no
        # reviewer can read, which is how a data change stops being reviewable.
        # ensure_ascii=False as well: the originals hold 'Amélie' as itself,
        # and escaping it would rewrite lines no preset touched.
        # A no-op run must be byte-identical, so the diff of a real run is the
        # dropped rows and nothing else: 2-space indent, non-ASCII kept as
        # itself ('Amélie'), and no trailing newline, which is how these
        # files are written.
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f'{path.name}: {dropped_total} dropped, {kept_total} kept'
          + (f'  {dict(dropped)}' if dropped else ''))
    return dropped_total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='rewrite the data files')
    parser.add_argument('--check', action='store_true', help='exit non-zero if anything is unclean')
    args = parser.parse_args()

    total = sum(clean_presets(path, args.write) for path in PRESET_FILES)

    if not total:
        print('\nEvery shipped identity is coherent.')
        return 0
    if args.write:
        print(f'\n{total} incoherent entr(ies) removed.')
        return 0
    print(f'\n{total} incoherent entr(ies). Run with --write to remove them.')
    return 1 if args.check else 0


if __name__ == '__main__':
    raise SystemExit(main())
