#!/usr/bin/env python3
"""Verify the font bundle, the per-OS fontconfig and fonts.json agree.

The invariant this guards: every family the Python launcher can REPORT for an
OS (pythonlib/camoufox/fonts.json[os], plus the essential / variant / marker
constants in pythonlib/camoufox/fingerprints.py) is a family the packaged
browser can RENDER under that OS's bundled fontconfig. A name that fails this
is a reverse leak: the page is told the font exists and then measures the
fallback.

For each OS it
  1. generates a runtime fonts.conf the way pythonlib/camoufox/utils.py does
     (the cwd-relative <dir> rewritten to an absolute bundle/fonts, which is the
     Linux package layout: fonts/{linux,windows,macos} plus the browser's own
     TwemojiMozilla.ttf) and runs fc-list against it;
  2. checks fonts.json[os] is a subset of what fc-list publishes, allowing the
     alias names bundle/fontconfig/<os>/fonts.conf rewrites (checked with
     fc-match: the alias must resolve to its bundled target);
  3. checks the CSS generics resolve to a family in fonts.json[os];
  4. checks every essential / variant / marker name is in fonts.json[os];
  5. draws _generate_random_font_subset a few times (when the camoufox package
     imports) and checks each draw is inside fonts.json[os] and contains the
     essentials and markers;
  6. checks scripts/package.py's flattening is safe: no basename collides
     across the OS dirs that share a package, and no OS dir has subfolders;
  7. lists files over GitHub's 100 MB push limit (a warning, not a failure).

Usage:  python3 scripts/verify-fonts.py [--bundle bundle] [--cache DIR] [--quick]
--quick skips the fc-list step (it builds a fontconfig cache over ~4 GB of
fonts the first time, which takes a few minutes).
Exit status is non-zero on any failure.
"""
import argparse
import ast
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSDIRS = {'win': 'windows', 'mac': 'macos', 'lin': 'linux'}
GENERICS = ['sans-serif', 'serif', 'monospace', 'cursive', 'fantasy', 'system-ui']
# Alias names each conf rewrites (pattern rules whose test is one of these).
GIB = 1024 ** 3
failures = []
warnings = []


def fail(msg):
    failures.append(msg)
    print('FAIL:', msg)


def warn(msg):
    warnings.append(msg)
    print('WARN:', msg)


def load_constants():
    """Read the font constants from fingerprints.py without importing it."""
    path = os.path.join(REPO, 'pythonlib', 'camoufox', 'fingerprints.py')
    tree = ast.parse(open(path, encoding='utf-8').read())
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if 'FONTS' in name and name.startswith('_'):
                consts[name] = ast.literal_eval(node.value)
    # The OS bases live in essential-fonts.json, shared with the TS launcher.
    with open(os.path.join(REPO, 'pythonlib', 'camoufox', 'essential-fonts.json'), encoding='utf-8') as f:
        for key, fonts in json.load(f).items():
            suffix = {'win': 'WINDOWS', 'mac': 'MACOS', 'lin': 'LINUX'}[key]
            consts[f'_ESSENTIAL_FONTS_{suffix}'] = fonts
    return consts


def conf_aliases(conf_text):
    """(alias -> target) for every <match target="pattern"> family rewrite."""
    out = {}
    for m in re.finditer(
        r'<match target="pattern">\s*<test qual="any" name="family">\s*<string>([^<]+)</string>\s*</test>\s*'
        r'<edit name="family" mode="assign" binding="same">\s*<string>([^<]+)</string>',
        conf_text,
    ):
        out[m.group(1)] = m.group(2)
    return out


def conf_alias_elements(conf_text):
    """Names rewritten by <alias> elements (stock 30-metric-aliases / urw-base35
    style): family -> list of candidate targets, in preference order. Which
    candidate wins depends on what is bundled, so the check accepts any
    reportable candidate."""
    out = {}
    for m in re.finditer(r'<alias[^>]*>\s*<family>([^<]+)</family>(.*?)</alias>', conf_text, re.S):
        cands = re.findall(r'<family>([^<]+)</family>', m.group(2))
        if cands:
            out.setdefault(m.group(1), []).extend(cands)
    return out


def runtime_conf(os_key, scan_dirs, cache_dir, tmpdir):
    """The conf this OS actually launches with.

    `scan_dirs` must be the group directories this OS reads, NOT the bundle root:
    fontconfig scans <dir> RECURSIVELY, so naming the root would let every OS
    reach every other OS's faces and the per-OS gate would go unchecked -- which
    is precisely what the group layout replaced the Windows reject globs with.
    utils._generate_fontconfig emits one <dir> per group for the same reason.
    """
    src = os.path.join(REPO, 'bundle', 'fontconfig', OSDIRS[os_key], 'fonts.conf')
    text = open(src, encoding='utf-8').read()
    marker = '<dir prefix="cwd">fonts</dir>'
    if marker not in text:
        fail(f'{os_key}: fonts.conf lacks {marker} (utils._generate_fontconfig rewrites exactly that)')
    dirs = ''.join(f'<dir>{d}</dir>' for d in scan_dirs)
    text = text.replace(marker, dirs)
    text = text.replace('<cachedir prefix="xdg">fontconfig</cachedir>', f'<cachedir>{cache_dir}</cachedir>')
    path = os.path.join(tmpdir, f'fonts-{os_key}.conf')
    open(path, 'w', encoding='utf-8').write(text)
    return path, text


def fc_pattern(name):
    # fc-match parses an unescaped '-' as the family/size separator, so
    # "sans-serif" would query family "sans" and "system-ui" family "system".
    return name.replace('\\', '\\\\').replace('-', '\\-').replace(':', '\\:')


def fc(cmd, conf):
    env = dict(os.environ, FONTCONFIG_FILE=conf)
    env.pop('FONTCONFIG_PATH', None)
    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=True).stdout



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
    ap.add_argument('--bundle', default=os.path.join(REPO, 'bundle'))
    ap.add_argument('--cache', default=None, help='fontconfig cache dir (default: a temp dir)')
    ap.add_argument('--quick', action='store_true', help='skip fc-list / fc-match')
    ap.add_argument('--draws', type=int, default=20)
    args = ap.parse_args()
    require_bundle(os.path.join(args.bundle, "fonts")
                   if not args.bundle.rstrip("/").endswith("fonts") else args.bundle)

    fonts_root = os.path.abspath(os.path.join(args.bundle, 'fonts'))
    fonts_json = json.load(open(os.path.join(REPO, 'pythonlib', 'camoufox', 'fonts.json'), encoding='utf-8'))
    consts = load_constants()

    # Browser-shipped fonts live beside the bundle in the package (fonts/ holds
    # TwemojiMozilla.ttf from the Firefox build plus the per-OS subdirs).
    extra_dirs = sorted({os.path.dirname(p) for p in glob.glob(os.path.join(REPO, 'camoufox-*', 'browser', 'fonts', 'TwemojiMozilla.ttf'))})[:1]
    if not extra_dirs:
        warn('no camoufox-*/browser/fonts/TwemojiMozilla.ttf found; "Twemoji Mozilla" is treated as browser-shipped')

    # 6. bundle layout. Each face is stored ONCE, in a directory named for the
    #    set of OSes that use it (L, M, W, LM, LW, MW, LMW). An OS reads the
    #    groups its letter appears in; macOS and Windows packages flatten those
    #    groups into one directory, so basenames must not collide within a
    #    package's group set.
    groups_file = os.path.join(fonts_root, 'groups.json')
    if not os.path.exists(groups_file):
        fail(f'{groups_file} is missing; run scripts/gen-font-groups.py')
        read_by, groups = {}, []
    else:
        with open(groups_file, encoding='utf-8') as fh:
            gj = json.load(fh)
        read_by, groups = gj.get('readBy', {}), gj.get('groups', [])

    names, digests = {}, {}
    for g in groups:
        d = os.path.join(fonts_root, g)
        if not os.path.isdir(d) or not os.listdir(d):
            fail(f'group {g}/ is missing or empty under {fonts_root}')
            continue
        names[g] = {}
        for dp, _dn, fn in os.walk(d):
            for f in fn:
                if dp != d:
                    fail(f'{g}/{os.path.relpath(os.path.join(dp, f), d)} is in a subfolder; '
                         f'package.py flattens groups for macOS/Windows')
                names[g].setdefault(f.lower(), []).append(f)
                fp = os.path.join(dp, f)
                size = os.path.getsize(fp)
                if size > 100 * 1024 * 1024:
                    # Not a defect: it is why the bundle ships as a release asset
                    # (2 GB per file) instead of repo content (100 MiB per file).
                    # Reported so the constraint stays visible to anyone who
                    # proposes tracking the fonts in git again.
                    print(f"note: {g}/{f} is {size / 1024 / 1024:.1f} MiB -- over GitHub's "
                          f"100 MiB in-repo limit, within the 2 GB release-asset limit")
                with open(fp, 'rb') as fh:
                    digests.setdefault(hashlib.sha256(fh.read()).hexdigest(), []).append(f'{g}/{f}')

    dupes = {h: v for h, v in digests.items() if len(v) > 1}
    if dupes:
        sample = sorted(dupes.values())[:3]
        fail(f'{len(dupes)} contents are stored more than once; the point of the group '
             f'layout is one copy per face: {sample}')
    elif digests:
        print(f'OK: {len(digests)} faces, each stored exactly once')

    # every OS must have somewhere to read from, and its flattened set must not clash
    for os_key in ('win', 'mac', 'lin'):
        gs = [g for g in read_by.get(os_key, []) if g in names]
        if not gs:
            fail(f'{os_key} reads no existing group')
            continue
        flat = {}
        for g in gs:
            for low in names[g]:
                flat.setdefault(low, []).append(g)
        clash = {k: v for k, v in flat.items() if len(v) > 1}
        if clash:
            fail(f'{os_key}: {len(clash)} basenames collide across {"+".join(gs)} '
                 f'(a flattened package would clobber): {sorted(clash)[:5]}')
        else:
            print(f'OK: {os_key} reads {"+".join(gs)} -- {len(flat)} files, no basename collisions')

    with tempfile.TemporaryDirectory(prefix='camoufox-verify-fonts-') as tmp:
        cache = args.cache or os.path.join(tmp, 'cache')
        os.makedirs(cache, exist_ok=True)
        for os_key, sub in OSDIRS.items():
            print(f'\n== {os_key} ({sub}/)')
            reportable = fonts_json[os_key]
            if reportable != sorted(reportable) or len(set(reportable)) != len(reportable):
                fail(f'{os_key}: fonts.json list is not sorted/unique')
            rset = set(reportable)
            scan = [os.path.join(fonts_root, g) for g in read_by.get(os_key, []) if g in names]
            if not scan:
                scan = [fonts_root]  # pre-groups bundle; utils.py falls back the same way
            conf, text = runtime_conf(os_key, [*scan, *extra_dirs], cache, tmp)
            aliases = conf_aliases(text)
            alias_elems = conf_alias_elements(text)

            # 4. constants
            suffix = {'win': 'WINDOWS', 'mac': 'MACOS', 'lin': 'LINUX'}[os_key]
            essential = consts[f'_ESSENTIAL_FONTS_{suffix}']
            markers = consts[f'_{suffix}_MARKER_FONTS']
            prob, variant = consts[f'_BASE_VARIANT_FONTS_{suffix}']
            for label, lst in (('essential', essential), ('marker', markers), ('variant', variant)):
                missing = sorted(set(lst) - rset)
                if missing:
                    fail(f'{os_key}: {label} names not in fonts.json: {missing}')
                else:
                    print(f'OK: {len(lst)} {label} names all in fonts.json[{os_key}] ({len(reportable)})')
            # A variant drawn with probability < 1 is a tier ON TOP of the base,
            # so it must be disjoint from it. At probability 1 there is only one
            # OS version left to spoof (Windows 10 was dropped 2026-09-22), the
            # variant IS part of that base, and the overlap is correct -- it is
            # then only used to subtract on a native host that lacks it.
            if prob < 1.0 and set(essential) & set(variant):
                fail(f'{os_key}: essential and variant overlap: {sorted(set(essential) & set(variant))}')
            # An unconditional pattern rewrite whose TARGET is reportable makes the
            # alias renderable for every identity, so the alias must be reported by
            # every identity too (essential). Rewrites to an unbundled/unreported
            # target are inert (the allowlist blocks the target) and only noted.
            skip = {'MS Shell Dlg 2', 'MONO', 'mono', 'sans', 'sans serif', *GENERICS}
            live = {a: t for a, t in aliases.items() if a not in skip and t in rset}
            inert = sorted(a for a, t in aliases.items() if a not in skip and t not in rset)
            not_always = sorted(set(live) - set(essential))
            if not_always:
                msg = (f'{os_key}: fonts.conf rewrites {not_always} unconditionally to a reportable target, '
                       f'so they render for every identity but are not always reported (_ESSENTIAL_FONTS_{suffix})')
                # Renderable-but-unreported is the safe direction of the invariant;
                # it is a hard failure only where the real OS reports the name
                # (Windows: every box resolves the GDI substitutes; macOS: the TTC
                # weight names are real families there).
                (fail if os_key in ('win', 'mac') else warn)(msg)
            elif live:
                print(f'OK: {len(live)} live alias rewrites are all essential (always reported)')
            if inert:
                print(f'note: {len(inert)} alias rewrites are inert for {os_key} (target not reportable): {inert[:4]}...')

            # 5. draws
            sys.path.insert(0, os.path.join(REPO, 'pythonlib'))
            try:
                from camoufox.fingerprints import _generate_random_font_subset  # noqa: E402
            except Exception as e:  # pragma: no cover - optional deps
                warn(f'camoufox package not importable ({e.__class__.__name__}: {e}); skipping draw check')
            else:
                target = {'win': 'windows', 'mac': 'macos', 'lin': 'linux'}[os_key]
                sizes = []
                for _ in range(args.draws):
                    draw = _generate_random_font_subset(target)
                    sizes.append(len(draw))
                    if len(set(draw)) != len(draw):
                        fail(f'{os_key}: draw has duplicates')
                    extra = sorted(set(draw) - rset)
                    if extra:
                        fail(f'{os_key}: draw reports names outside fonts.json: {extra[:5]}')
                    missing = sorted((set(essential) | set(markers)) - set(draw))
                    if missing:
                        fail(f'{os_key}: draw lacks essential/marker names: {missing[:5]}')
                    vs = set(variant) & set(draw)
                    if vs and vs != set(variant):
                        fail(f'{os_key}: variant drawn partially: {sorted(vs)}')
                print(f'OK: {args.draws} draws inside fonts.json; sizes {min(sizes)}..{max(sizes)} of {len(reportable)} (base {len(essential)})')

            if args.quick:
                continue

            # 1./2. fc-list
            out = fc(['fc-list', '--format', '%{family}\n'], conf)
            published = set()
            for line in out.splitlines():
                for fam in line.split(','):
                    fam = fam.strip()
                    if fam:
                        published.add(fam)
            pub_lower = {f.lower() for f in published}
            print(f'fc-list publishes {len(published)} families under the {os_key} conf')

            # 2b. the group gate itself. Everything above only proves an OS can
            #     render what it reports; this proves it CANNOT reach what it must
            #     not. That direction is invisible to fonts.json and to the draw
            #     tests, and it is the whole reason the groups exist: a face is
            #     kept out of an identity's reach by not being in a group that
            #     identity reads. If the root leaked in, an emoji or CJK glyph
            #     could fall back to Segoe UI Emoji / PingFang on a machine
            #     claiming Linux -- a leak no reported name would reveal.
            allowed = {os.path.realpath(d) for d in [*scan, *extra_dirs]}
            scanned = {line.strip() for line in
                       fc(['fc-list', '--format', '%{file}\n'], conf).splitlines() if line.strip()}
            stray = sorted(f for f in scanned
                           if os.path.realpath(os.path.dirname(f)) not in allowed)
            if stray:
                fail(f'{os_key}: fontconfig reaches {len(stray)} faces outside the groups '
                     f'{os_key} reads -- they are glyph-fallback candidates for this '
                     f'identity: {[os.path.relpath(f, fonts_root) for f in stray[:5]]}')
            else:
                print(f'OK: {len(scanned)} faces reachable, all inside '
                      f'{"+".join(g for g in read_by.get(os_key, []) if g in names) or "fonts/"}')
            unrenderable = [f for f in reportable if f.lower() not in pub_lower]
            resolved = []
            for name in list(unrenderable):
                if name in aliases:
                    got = fc(['fc-match', '--format', '%{family}\n', fc_pattern(name)], conf).split(',')[0].strip()
                    if got.lower() == aliases[name].lower() and aliases[name] in rset:
                        resolved.append((name, got))
                        unrenderable.remove(name)
                    else:
                        fail(f'{os_key}: alias {name} resolves to {got!r}, expected {aliases[name]!r} (must be in fonts.json)')
                elif name in alias_elems:
                    got = fc(['fc-match', '--format', '%{family}\n', fc_pattern(name)], conf).split(',')[0].strip()
                    if got.lower() != name.lower() and got in rset:
                        resolved.append((name, got))
                        unrenderable.remove(name)
                    else:
                        fail(f'{os_key}: <alias> {name} resolves to {got!r}, not a reportable candidate of {alias_elems[name][:3]}')
                elif name == 'Twemoji Mozilla' and not extra_dirs:
                    unrenderable.remove(name)  # browser-shipped; see warning above
            if unrenderable:
                fail(f'{os_key}: {len(unrenderable)} fonts.json names fc-list does not publish: {unrenderable[:10]}')
            else:
                print(f'OK: all {len(reportable)} fonts.json[{os_key}] names are published or alias-resolved ({len(resolved)} aliases)')
            for name, got in resolved:
                print(f'   alias {name} -> {got}')
            unreported = sorted(published - rset)
            print(f'note: {len(unreported)} published families are not reportable (pruned by the allowlist)')

            # 3. generics (+ the Windows dialog family)
            for g in GENERICS + (['MS Shell Dlg 2'] if os_key == 'win' else []):
                got = fc(['fc-match', '--format', '%{family}\n', fc_pattern(g)], conf).split(',')[0].strip()
                if got in rset:
                    print(f'OK: {g} -> {got}')
                elif g == 'system-ui':
                    # Gecko resolves system-ui itself (the platform UI font /
                    # font.name-list.system-ui); the fontconfig rule is advisory.
                    print(f'note: {g} -> {got!r} (not reportable; Gecko resolves system-ui itself)')
                else:
                    fail(f'{os_key}: {g} resolves to {got!r}, which is not in fonts.json[{os_key}]')
            # rejects and scan-time families in the windows conf
            if os_key == 'win':
                for fam in ('Sitka Small', 'Segoe UI Variable Text'):
                    if fam.lower() not in pub_lower:
                        fail(f'win: scan-time family {fam} not published (check the <match target="scan"> block)')
                    else:
                        print(f'OK: scan-time family {fam} published')
                rejected = re.findall(r'<glob>\*/fonts/windows/([^<]+)</glob>', text)
                if rejected:
                    files = set()
                    for g in read_by.get('win', []):
                        gd = os.path.join(fonts_root, g)
                        if os.path.isdir(gd):
                            files |= set(os.listdir(gd))
                    dangling = [r for r in rejected if r not in files]
                    if dangling:
                        warn(f'win: {len(dangling)} reject globs name files not in any Windows group: {dangling[:5]}')
                for r in []:
                    if '[' in r:
                        warn(f'win: reject glob {r!r} contains [ ] which fontconfig treats as a character class')

    print()
    for w in warnings:
        print('WARN:', w)
    if failures:
        print(f'\n{len(failures)} FAILURE(S)')
        for f_ in failures:
            print(' -', f_)
        sys.exit(1)
    print('\nALL CHECKS PASSED')


if __name__ == '__main__':
    main()
