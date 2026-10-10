#!/usr/bin/env python3
"""Regenerate python/src/camoufox/font-groups.json from the per-OS font manifest.

The manifest (scripts/data/font-manifests.json) models a real machine's font set
as ONE OS-version base plus independent additions, and it distinguishes two kinds
of addition because real users install them differently:

    kind "bundle"    branded software whose fonts arrive as one indivisible
                     download (Office, LibreOffice, the Pan-European FOD pack).
                     Present or absent as a unit, at its own probability.
    kind "alacarte"  a category people install piecemeal (developer and web
                     fonts). Present at its own probability, and then only
                     `sizes` of its members are actually installed.

font-groups.json is that model projected onto the families Camoufox can really
report: each unit's font list is intersected with fonts.json, which is itself
generated from the bundle (scripts/gen-fonts-json.py). Emitting it here rather
than maintaining it by hand is what keeps the draw's probabilities equal to the
manifest's, and it is why `prob`, `requiresLocale` and `sizes` survive the trip
-- the previous hand-written file kept only {id, fonts}, so the draw had no
choice but to treat every unit as equally likely.

Usage (after the bundle or the manifest changed, and AFTER gen-fonts-json.py):
    python3 scripts/gen-font-groups.py
"""

import argparse
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(os.path.dirname(REPO), 'python', 'src', 'camoufox')
OS_KEYS = ('win', 'mac', 'lin')


def build_bases(manifest, reportable):
    """The reportable projection of each OS's VERSION BASES, with their weights.

    A real machine has exactly one OS-version base, in full: only the additions
    vary from box to box. Windows 11's base is Windows 10's plus a handful of
    families, but macOS 26's is not a superset of Sonoma's -- each has families
    the other does not -- so the bases have to be drawn as whole alternatives
    rather than as "core plus the newer version's extras".
    """
    out = {}
    for os_key in OS_KEYS:
        pool = set(reportable.get(os_key, []))
        bases = []
        for base_id, base in manifest[os_key]['bases'].items():
            if not base.get('weight'):
                continue
            fonts = [f for f in base['fonts'] if f in pool]
            if not fonts:
                continue
            bases.append({'id': base_id, 'weight': base['weight'], 'fonts': fonts})
        total = sum(b['weight'] for b in bases)
        if total:
            for b in bases:
                b['weight'] = round(b['weight'] / total, 6)
        out[os_key] = bases
    return out


def build(manifest, reportable):
    """The reportable projection of each OS's additions, in manifest order."""
    out = {}
    for os_key in OS_KEYS:
        pool = set(reportable.get(os_key, []))
        units = []
        for addition in manifest[os_key]['additions']:
            fonts = [f for f in addition['fonts'] if f in pool]
            if not fonts:
                # Nothing this unit names can be reported under this OS, so a
                # draw could never produce it; leaving it out keeps the file a
                # faithful list of what can actually happen.
                continue
            unit = {
                'id': addition['id'],
                'kind': addition['kind'],
                'prob': addition['prob'],
                'fonts': fonts,
            }
            if addition.get('requiresLocale'):
                unit['requiresLocale'] = addition['requiresLocale']
            if addition['kind'] == 'alacarte':
                # Renormalise the size distribution over what survives the
                # intersection: a category whose 32 names came down to 9 cannot
                # install 12 of them.
                sizes = [s for s in addition.get('sizes', []) if s['n'] <= len(fonts)]
                if not sizes:
                    sizes = [{'n': len(fonts), 'w': 1.0}]
                total = sum(s['w'] for s in sizes)
                unit['sizes'] = [{'n': s['n'], 'w': round(s['w'] / total, 6)} for s in sizes]
            units.append(unit)
        out[os_key] = units
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', default=os.path.join(REPO, 'scripts', 'data', 'font-manifests.json'))
    ap.add_argument('--fonts', default=os.path.join(PACKAGE, 'fonts.json'))
    ap.add_argument('--out', default=os.path.join(PACKAGE, 'font-groups.json'))
    ap.add_argument('--out-bases', default=os.path.join(PACKAGE, 'font-bases.json'))
    args = ap.parse_args()

    with open(args.manifest) as fh:
        manifest = json.load(fh)
    with open(args.fonts) as fh:
        reportable = json.load(fh)

    groups = build(manifest, reportable)
    with open(args.out, 'w') as fh:
        json.dump(groups, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write('\n')

    bases = build_bases(manifest, reportable)
    with open(args.out_bases, 'w') as fh:
        json.dump(bases, fh, indent=1, ensure_ascii=False, sort_keys=False)
        fh.write('\n')

    for os_key in OS_KEYS:
        for b in bases[os_key]:
            print('%s: base %-10s weight=%-8s %d families' % (os_key, b['id'], b['weight'], len(b['fonts'])))
        units = groups[os_key]
        bundles = [u for u in units if u['kind'] == 'bundle']
        alacarte = [u for u in units if u['kind'] == 'alacarte']
        print('%s: %d units (%d bundle, %d alacarte), %d families'
              % (os_key, len(units), len(bundles), len(alacarte),
                 sum(len(u['fonts']) for u in units)))
        for u in units:
            extra = ''
            if u.get('requiresLocale'):
                extra = ' locale=%s' % u['requiresLocale']
            if u['kind'] == 'alacarte':
                exp = sum(s['n'] * s['w'] for s in u['sizes'])
                extra += ' E[n]=%.2f of %d' % (exp, len(u['fonts']))
            print('    %-14s %-9s p=%-6s n=%-3d%s'
                  % (u['id'], u['kind'], u['prob'], len(u['fonts']), extra))
    print('wrote %s' % args.out)
    print('wrote %s' % args.out_bases)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
