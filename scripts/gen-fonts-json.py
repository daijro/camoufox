#!/usr/bin/env python3
"""Regenerate pythonlib/camoufox/fonts.json FROM the actual bundled fonts.

fonts.json[os] is the pool the per-launch font draw reports from
(fingerprints._generate_random_font_subset) and the list update_fonts() merges
in for callers that pass their own `fonts=`. Every name in it MUST be a family
the packaged browser can render under that OS's bundled fontconfig, or the
browser reports a font it cannot draw (a reverse leak). So this script reads
the group directories that OS reads with fc-scan (bundle/fonts/groups.json
stores each face once, under the set of OSes that use it), and then keeps only
the names the per-OS
font manifest (scripts/data/font-manifests.json) can ever report:

  reportable[os] = fc-scan(the groups <os> reads)         # what fontconfig publishes
                 + SCAN_FAMILIES additions                 # opsz instance families
                 + ALIASES (rewritten by fonts.conf)       # Courier -> Courier New ...
                 + SHIPPED_BY_BROWSER                      # Twemoji Mozilla
                 INTERSECT names(font-manifests.json)      # bases + additions + MARKER_FONTS
                 + REPORTABLE_EXTRA                        # camoufox-only additions

The intersection is deliberate: the bundle carries families a real OS never
presents as families (weight-variant subfamilies such as "Barlow Black" that
DirectWrite folds into "Barlow", the bare "Sitka" and "Segoe UI Variable"
umbrella names, CJK families a stock Windows install does not report), and
those stay renderable but are never reported. The renderable-but-unreported names
are written next to the output (fonts.json.unreported.txt is NOT produced in
the package; pass --dump-union to see them) so the gap stays visible.

Usage (build machine, after the bundle changed):
    python3 scripts/gen-fonts-json.py [--bundle bundle/fonts]
                                      [--out pythonlib/camoufox/fonts.json]
                                      [--manifest scripts/data/font-manifests.json]
                                      [--print-bases] [--dump-union DIR]

The manifest lists, per OS, the base font sets of each OS version (with their
real-world share) and the optional additions (Office, LibreOffice, developer
and web fonts) with their install probability, per OS. --print-bases prints
the OS base lists (intersected with the result) and writes the essential floor
to pythonlib/camoufox/essential-fonts.json, which both launchers read and which
must be kept in step with this file.
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSDIRS = {'win': 'windows', 'mac': 'macos', 'lin': 'linux'}
FONT_EXT = ('.ttf', '.otf', '.ttc', '.dfont')

# Mirrors the <match target="scan"> block in bundle/fontconfig/windows/fonts.conf.
SCAN_FAMILIES = {
    'win': {
        'Sitka': ['Sitka Small', 'Sitka Subheading', 'Sitka Heading', 'Sitka Display', 'Sitka Banner'],
        'Segoe UI Variable': ['Segoe UI Variable Small', 'Segoe UI Variable Text', 'Segoe UI Variable Display'],
    },
    'mac': {},
    'lin': {},
}

# Mirrors the alias block in bundle/fontconfig/windows/fonts.conf: names with no
# file of their own that fonts.conf rewrites to a bundled target. The target
# MUST be bundled.
ALIASES = {
    'win': {
        'Courier': 'Courier New',
        'Helvetica': 'Arial',
        'MS Sans Serif': 'Microsoft Sans Serif',
        'Small Fonts': 'Arial',
        'MS Serif': 'Times New Roman',
        'Roman': 'Times New Roman',
        'Times': 'Times New Roman',
        'Calibri Light': 'Calibri',
        'Candara Light': 'Candara',
        'Corbel Light': 'Corbel',
        'Leelawadee UI Semilight': 'Leelawadee UI',
        'Nirmala Text Semilight': 'Nirmala UI',
        'Nirmala UI Semilight': 'Nirmala UI',
    },
    # macOS registers each weight of these TTCs as its own family name, so a
    # real Mac reports them (they are in the macOS base manifest); fontconfig
    # only registers the base family, and the <match target="pattern"> block in
    # bundle/fontconfig/macos/fonts.conf rewrites each to it. fc-scan cannot see
    # these eight, so they are listed here and reported always (they are in
    # _ESSENTIAL_FONTS_MACOS), which is what the real base does. The PingFang
    # Light and MuktaMahee rewrites in that block are not listed: PingFang is
    # not bundled, and "MuktaMahee Regular" is a scanned family already.
    'mac': {
        'American Typewriter Semibold': 'American Typewriter',
        'Apple SD Gothic Neo ExtraBold': 'Apple SD Gothic Neo',
        'Futura Bold': 'Futura',
        'InaiMathi Bold': 'InaiMathi',
        'Kohinoor Devanagari Medium': 'Kohinoor Devanagari',
        'Noto Sans Canadian Aboriginal Regular': 'Noto Sans Canadian Aboriginal',
        'STIX Two Math Regular': 'STIX Two Math',
        'STIX Two Text Regular': 'STIX Two Text',
    },
    # The same block is copied into the linux conf, where one rewrite is live
    # ("Noto Sans Canadian Aboriginal Regular"). A real Ubuntu does not report
    # that name, so it stays unreported there; scripts/verify-fonts.py warns.
    # Metric-compatible aliases every stock Linux fontconfig ships
    # (30-metric-aliases.conf, copied into bundle/fontconfig/linux/fonts.conf):
    # a page asking for Arial gets Liberation Sans at Arial's exact metrics, so
    # a real Ubuntu Firefox "has" these names. Targets are all bundled.
    'lin': {
        'Arial': 'Liberation Sans',
        'Arial Narrow': 'Liberation Sans Narrow',
        'Helvetica': 'Liberation Sans',
        'Helvetica Narrow': 'Nimbus Sans Narrow',
        'Times': 'Liberation Serif',
        'Times New Roman': 'Liberation Serif',
        'Courier': 'Liberation Mono',
        'Courier New': 'Liberation Mono',
        'Calibri': 'Carlito',
        'Cambria': 'Caladea',
        'Palatino': 'P052',
        'Palatino Linotype': 'P052',
        'Bookman Old Style': 'URW Bookman',
        'Century Schoolbook': 'C059',
        'Avant Garde': 'URW Gothic',
        'Zapf Chancery': 'Z003',
        'Symbol': 'Standard Symbols PS',
    },
}

# Families the BROWSER ships (dist/bin/fonts/TwemojiMozilla.ttf, staged by the
# Firefox build into the same fonts/ dir the bundled fontconfig scans), so an
# fc-scan over bundle/fonts cannot see them. The manifest lists it for win only
# (it is in the Windows base, measured); lin keeps camoufox's long-standing
# CreepJS marker.
SHIPPED_BY_BROWSER = {'win': ['Twemoji Mozilla'], 'mac': [], 'lin': ['Twemoji Mozilla']}

# The CreepJS OS-marker families the font draw adds back after the random
# subset (when bundled). They are reportable even when no base or addition
# names them, so they count as wanted here. Twin of _*_MARKER_FONTS in
# pythonlib/camoufox/fingerprints.py.
MARKER_FONTS = {
    'win': ['Segoe UI', 'Tahoma', 'Cambria Math', 'Nirmala UI'],
    'mac': ['Helvetica Neue', 'PingFang HK', 'PingFang SC', 'PingFang TC'],
    'lin': ['Noto Sans', 'Noto Serif', 'DejaVu Sans Mono', 'Arimo', 'Cousine', 'Tinos', 'Twemoji Mozilla'],
}

# Reportable names that are NOT in the manifest for that OS. Each entry is a
# deliberate camoufox deviation and must be renderable (checked below).
REPORTABLE_EXTRA = {
    'win': [],
    'mac': [],
    # Firefox exposes its bundled Twemoji Mozilla to content on Linux; it has
    # been a _LINUX_MARKER_FONTS entry since the font draw was introduced.
    'lin': ['Twemoji Mozilla'],
}



def bundle_dirs_for(bundle, os_key, sub):
    """The directories this OS renders from: its groups, else the old per-OS dir."""
    groups = os.path.join(bundle, 'groups.json')
    if os.path.exists(groups):
        with open(groups, encoding='utf-8') as fh:
            read_by = json.load(fh).get('readBy', {}).get(os_key, [])
        dirs = [os.path.join(bundle, g) for g in read_by if os.path.isdir(os.path.join(bundle, g))]
        if dirs:
            return dirs
    return [os.path.join(bundle, sub)]


def scan_families(directory):
    """Families fontconfig publishes from one directory, or several.

    The bundle stores each face once, in a directory named for the set of OSes
    that use it (bundle/fonts/groups.json), so an OS's renderable set is the
    union of the groups its letter appears in -- not one per-OS directory.
    """
    directories = [directory] if isinstance(directory, str) else list(directory)
    files = []
    for d in directories:
        if not os.path.isdir(d):
            sys.exit(f'bundle dir missing: {d}')
        for dp, _dn, fn in os.walk(d):
            for f in fn:
                if f.lower().endswith(FONT_EXT):
                    files.append(os.path.join(dp, f))
    if not files:
        sys.exit(f'no font files under {directories} (is the bundle restored?)')
    fams = set()
    # fc-scan takes many files at once; chunk to keep argv bounded.
    for i in range(0, len(files), 200):
        out = subprocess.run(
            ['fc-scan', '--format', '%{family}\n', *files[i:i + 200]],
            capture_output=True, text=True, check=True,
        ).stdout
        for line in out.splitlines():
            for fam in line.split(','):
                fam = fam.strip()
                if fam:
                    fams.add(fam)
    return fams


def load_manifest(args):
    with open(args.manifest, encoding='utf-8') as fh:
        return json.load(fh)


def manifest_names(man, os_key):
    names = set()
    for base in man[os_key]['bases'].values():
        names.update(base['fonts'])
    for add in man[os_key]['additions']:
        names.update(add['fonts'])
    return names



def require_bundle(bundle):
    """The font bundle is a release asset; fail with the fix, not a stack trace."""
    if os.path.isdir(bundle) and os.listdir(bundle):
        return
    sys.exit(
        f'font bundle not present at {bundle}.\n'
        f'It ships as a release asset rather than repo content (~2.1 GB); run:\n'
        f'    make fonts-extract\n'
        f'See scripts/fetch-fonts.py for why it is not in git.'
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bundle', default=os.path.join(REPO, 'bundle', 'fonts'))
    ap.add_argument('--out', default=os.path.join(REPO, 'pythonlib', 'camoufox', 'fonts.json'))
    ap.add_argument('--manifest', default=os.path.join(REPO, 'scripts', 'data', 'font-manifests.json'),
                    help='per-OS font manifest (bases + additions)')
    ap.add_argument('--print-bases', action='store_true', help='print OS base lists as Python literals')
    ap.add_argument('--dump-union', default=None, help='dir to write <os>-union.txt / <os>-unreported.txt')
    args = ap.parse_args()
    require_bundle(os.path.join(args.bundle, "fonts")
                   if not args.bundle.rstrip("/").endswith("fonts") else args.bundle)

    man = load_manifest(args)
    result = {}
    bases_out = {}
    for os_key, sub in OSDIRS.items():
        union = scan_families(bundle_dirs_for(args.bundle, os_key, sub))
        for src, added in SCAN_FAMILIES[os_key].items():
            if src in union:
                union.update(added)
        for name, target in ALIASES[os_key].items():
            if target not in union:
                sys.exit(f'{os_key}: alias {name} -> {target}: target is not bundled')
            union.add(name)
        union.update(SHIPPED_BY_BROWSER[os_key])

        wanted = manifest_names(man, os_key) | set(MARKER_FONTS[os_key])
        reportable = union & wanted
        # An alias is rewritten unconditionally by fonts.conf, so it is renderable
        # for every identity whose list has the target; report it always (the
        # bases below carry it, and the real OS resolves every one of them).
        reportable |= set(ALIASES[os_key])
        # Families whose mere presence makes CreepJS-class detectors infer
        # Windows 11 (measured 2026-09-14: a Linux identity that drew Cascadia
        # was read as "Windows 11 vs UA Linux"). The manifest models them as a
        # rare developer install on Linux/macOS; the detector cost outweighs the
        # realism, so they are never reported (or rendered) off Windows.
        if os_key in ('lin', 'mac'):
            reportable -= {'Cascadia Code', 'Cascadia Mono', 'Cascadia Code PL', 'Cascadia Mono PL'}
        for name in REPORTABLE_EXTRA[os_key]:
            if name not in union:
                sys.exit(f'{os_key}: REPORTABLE_EXTRA {name} is not renderable')
            reportable.add(name)
        unbundled = sorted(wanted - union)
        unreported = sorted(union - reportable)
        result[os_key] = sorted(reportable)
        print(f'{os_key}: {len(union)} renderable families from '
              f'{"+".join(os.path.basename(d) for d in bundle_dirs_for(args.bundle, os_key, sub))}, '
              f'{len(result[os_key])} reportable, {len(unreported)} renderable-but-unreported, '
              f'{len(unbundled)} manifest names unbundled', file=sys.stderr)
        if args.dump_union:
            os.makedirs(args.dump_union, exist_ok=True)
            for tag, data in (('union', sorted(union)), ('unreported', unreported), ('unbundled', unbundled)):
                with open(os.path.join(args.dump_union, f'{os_key}-{tag}.txt'), 'w', encoding='utf-8') as fh:
                    fh.write('\n'.join(data) + '\n')
        bases_out[os_key] = {
            key: sorted((set(base['fonts']) & reportable) | set(ALIASES[os_key]))
            for key, base in man[os_key]['bases'].items()
            if base['fonts'] and not base.get('deferred')
        }

    with open(args.out, 'w', encoding='utf-8') as fh:
        # Same shape as before: {"win": [...], "mac": [...], "lin": [...]}, each
        # list sorted, tab-indented and wrapped so diffs stay reviewable.
        fh.write('{\n')
        for i, os_key in enumerate(('win', 'mac', 'lin')):
            rows, row = [], []
            for name in result[os_key]:
                row.append(json.dumps(name, ensure_ascii=False))
                if len(', '.join(row)) > 88:
                    rows.append('\t\t' + ', '.join(row))
                    row = []
            if row:
                rows.append('\t\t' + ', '.join(row))
            fh.write(f'\t"{os_key}": [\n' + ',\n'.join(rows) + '\n\t]' + (',' if i < 2 else '') + '\n')
        fh.write('}\n')
    print(f'wrote {args.out}', file=sys.stderr)

    if args.print_bases:
        for os_key, bases in bases_out.items():
            for key, fonts in bases.items():
                print(f'# {os_key} base {key}: {len(fonts)} families')
                print(json.dumps(fonts, ensure_ascii=False))
        # additions pools, for the record
        for os_key in OSDIRS:
            base_all = set()
            for b in bases_out[os_key].values():
                base_all.update(b)
            print(f'# {os_key} additions pool (reportable minus every base): {len(set(result[os_key]) - base_all)}')

        # _ESSENTIAL_FONTS_* is the floor UNDER whichever base was drawn, so it
        # is the INTERSECTION of the bases, not any one of them. Making it a
        # superset of one base silently forces that base's exclusive families
        # onto every identity -- which is what made a macOS 26 identity keep
        # claiming 131 Sonoma-only families -- and it must still carry the alias
        # names fonts.conf rewrites unconditionally, which always render.
        essential = {}
        for os_key in OSDIRS:
            bases = list(bases_out[os_key].values())
            if not bases:
                continue
            common = set(bases[0])
            for b in bases[1:]:
                common &= set(b)
            common |= set(ALIASES[os_key])
            common &= set(result[os_key])
            suffix = {'win': 'WINDOWS', 'mac': 'MACOS', 'lin': 'LINUX'}[os_key]
            print(f'# _ESSENTIAL_FONTS_{suffix}: {len(common)} families '
                  f'(intersection of {len(bases)} base(s) + aliases)')
            essential[os_key] = sorted(common)
        path = os.path.join(REPO, 'pythonlib', 'camoufox', 'essential-fonts.json')
        # Both launchers read every OS's list at import, so a file missing one
        # breaks `import camoufox`. Keep the old file rather than write that.
        missing = [k for k in OSDIRS if k not in essential]
        if missing:
            sys.exit(f'not writing {path}: no OS bases for {", ".join(missing)} '
                     f'in the manifest')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{\n' + ',\n'.join(f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}'
                                        for k, v in essential.items()) + '\n}\n')
        print(f'wrote {path}')


if __name__ == '__main__':
    main()
