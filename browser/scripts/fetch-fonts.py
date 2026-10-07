#!/usr/bin/env python3
"""Fetch the font bundle, which is a release asset rather than repo content.

WHY IT IS NOT IN GIT
--------------------
The bundle is ~2.1 GB of font binaries. Committing it, even compressed, is the
wrong trade:

  * GitHub rejects any file over 100 MiB, so a single archive would have to be
    split into ~9 parts (the bundle is ~770 MB as .tar.xz).
  * An xz archive cannot be delta-compressed, so EVERY font update would append
    another ~770 MB blob to history, permanently, paid by anyone who clones the
    repo to fix a typo.

Release assets allow 2 GB per file, so one asset holds the whole bundle with no
splitting, no Git LFS, and no history growth. This is the same trust model the
build already uses for the Firefox source itself (`make fetch` pulls a ~500 MB
tarball from archive.mozilla.org), so a clone has never been buildable offline
anyway.

What IS tracked is `scripts/data/font-bundle.json`: the asset name, its size and
its sha256. That pins exactly which bundle a given commit expects, so the build
is reproducible even though the bytes live elsewhere -- and a mismatched or
truncated download fails loudly here instead of silently producing a browser
that reports fonts it cannot render.

Only the compressed archive is kept. `bundle/fonts/` is extracted on demand and
is gitignored; `--extract` materialises it, `--clean` removes it again.

Usage:
    python3 scripts/fetch-fonts.py            # download + verify the archive
    python3 scripts/fetch-fonts.py --extract  # ...and unpack to bundle/fonts/
    python3 scripts/fetch-fonts.py --check    # verify only; non-zero if absent
    python3 scripts/fetch-fonts.py --clean    # drop the extracted directory
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(REPO, 'scripts', 'data', 'font-bundle.json')
BUNDLE_DIR = os.path.join(REPO, 'bundle')


def load_spec():
    if not os.path.exists(SPEC):
        sys.exit(f'missing {SPEC}; the font bundle spec is required')
    with open(SPEC, encoding='utf-8') as fh:
        return json.load(fh)


def digest(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(chunk), b''):
            h.update(block)
    return h.hexdigest()


def archive_path(spec):
    return os.path.join(BUNDLE_DIR, spec['asset'])


def stamp_path():
    return os.path.join(BUNDLE_DIR, 'fonts', '.bundle-sha256')


def already_extracted(spec):
    """True when bundle/fonts/ was unpacked from exactly the pinned archive.

    Lets `--extract` gate anything that needs the fonts present (scripts/stage-fonts.sh
    runs before every `make run`) without re-decompressing 2.1 GB, or even
    needing the archive to still be on disk. A bundle bump changes the sha256,
    so the stale tree is replaced rather than trusted.
    """
    if not os.path.exists(os.path.join(BUNDLE_DIR, 'fonts', 'groups.json')):
        return False
    try:
        with open(stamp_path(), encoding='utf-8') as fh:
            return fh.read().strip() == spec['sha256']
    except OSError:
        return False


def verify(spec, path, quiet=False):
    """True when `path` is the archive this commit expects."""
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    if spec.get('size') and size != spec['size']:
        if not quiet:
            print(f'size mismatch: have {size}, expected {spec["size"]}', file=sys.stderr)
        return False
    got = digest(path)
    if got != spec['sha256']:
        if not quiet:
            print(f'sha256 mismatch:\n  have     {got}\n  expected {spec["sha256"]}', file=sys.stderr)
        return False
    return True


def download(spec, path):
    url = spec['url']
    print(f'fetching {url}', file=sys.stderr)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.part'
    # aria2c is already a build dependency (see scripts/install-deps.sh); fall
    # back to curl so a checkout without it can still fetch.
    if shutil.which('aria2c'):
        cmd = ['aria2c', '-x8', '-s8', '-k1M', '--allow-overwrite=true',
               '-d', os.path.dirname(tmp), '-o', os.path.basename(tmp), url]
    elif shutil.which('curl'):
        cmd = ['curl', '-fL', '--retry', '3', '-o', tmp, url]
    else:
        sys.exit('neither aria2c nor curl is available to download the font bundle')
    if subprocess.run(cmd).returncode != 0:
        sys.exit('font bundle download failed')
    os.replace(tmp, path)


def extract(spec, path):
    target = os.path.join(BUNDLE_DIR, 'fonts')
    if os.path.isdir(target):
        shutil.rmtree(target)
    print(f'extracting {os.path.basename(path)} -> bundle/fonts/', file=sys.stderr)
    with tarfile.open(path, 'r:xz') as tf:
        # The archive is pinned by sha256 above, so its members are trusted;
        # still refuse anything that escapes the bundle directory.
        for member in tf.getmembers():
            dest = os.path.realpath(os.path.join(BUNDLE_DIR, member.name))
            if not dest.startswith(os.path.realpath(BUNDLE_DIR) + os.sep):
                sys.exit(f'refusing to extract outside bundle/: {member.name}')
        tf.extractall(BUNDLE_DIR)

    # The v1 archive was built while 000_README.txt and cleanfonts.sh still sat
    # inside bundle/fonts/. They are tracked at bundle/FONTS-README.txt and
    # scripts/cleanfonts.sh now, so an extracted copy is a stale duplicate of a
    # file git owns -- harmless (bundle/fonts/ is ignored) but confusing, and it
    # would be folded back in if the bundle were rebuilt from this tree. Prune
    # them; a future archive simply will not contain them.
    for stray in ('000_README.txt', 'cleanfonts.sh'):
        p = os.path.join(target, stray)
        if os.path.exists(p):
            os.remove(p)

    # Records WHICH archive this tree came from, so a later --extract can skip
    # the work instead of repeating it. Written last: a crash mid-extract leaves
    # no stamp, so the partial tree is re-done rather than used.
    with open(stamp_path(), 'w', encoding='utf-8') as fh:
        fh.write(spec['sha256'] + '\n')

    n = sum(len(f) for _, _, f in os.walk(target))
    print(f'extracted {n} files', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--extract', action='store_true', help='unpack to bundle/fonts/ after verifying')
    ap.add_argument('--check', action='store_true', help='verify only; exit non-zero if missing/corrupt')
    ap.add_argument('--clean', action='store_true', help='remove the extracted bundle/fonts/ directory')
    ap.add_argument('--force', action='store_true', help='re-download even if the archive verifies')
    ap.add_argument('--write-spec', metavar='ARCHIVE',
                    help='record a locally built archive in font-bundle.json (size + sha256), '
                         'for publishing a new bundle release')
    ap.add_argument('--tag', default=None, help='release tag to point --write-spec at')
    args = ap.parse_args()

    if args.write_spec:
        src = args.write_spec
        if not os.path.exists(src):
            sys.exit(f'no such archive: {src}')
        existing = json.load(open(SPEC, encoding='utf-8')) if os.path.exists(SPEC) else {}
        tag = args.tag or existing.get('tag') or 'font-bundle-v1'
        asset = os.path.basename(src)
        spec = {
            'tag': tag,
            'asset': asset,
            'size': os.path.getsize(src),
            'sha256': digest(src),
            'url': existing.get('urlTemplate', 'https://github.com/{repo}/releases/download/{tag}/{asset}')
                   .format(repo=existing.get('repo', 'JWriter20/camoufox'), tag=tag, asset=asset),
            'repo': existing.get('repo', 'JWriter20/camoufox'),
            'urlTemplate': 'https://github.com/{repo}/releases/download/{tag}/{asset}',
            'note': 'The font bundle is a release asset, not repo content. '
                    'See scripts/fetch-fonts.py. Regenerate with --write-spec after rebuilding it.',
        }
        os.makedirs(os.path.dirname(SPEC), exist_ok=True)
        with open(SPEC, 'w', encoding='utf-8') as fh:
            json.dump(spec, fh, indent=1)
            fh.write('\n')
        print(f'wrote {SPEC}')
        print(f'  asset  {asset}  ({spec["size"] / 1e6:.0f} MB)')
        print(f'  sha256 {spec["sha256"]}')
        print(f'  url    {spec["url"]}')
        return 0

    spec = load_spec()
    path = archive_path(spec)

    if args.clean:
        target = os.path.join(BUNDLE_DIR, 'fonts')
        if os.path.isdir(target):
            shutil.rmtree(target)
            print('removed bundle/fonts/', file=sys.stderr)
        return 0

    if args.check:
        if verify(spec, path):
            print(f'OK: {spec["asset"]} matches font-bundle.json')
            return 0
        print(f'font bundle missing or corrupt: run `make fetch-fonts` '
              f'(expected {spec["asset"]}, sha256 {spec["sha256"][:12]}...)', file=sys.stderr)
        return 1

    if args.extract and not args.force and already_extracted(spec):
        print(f'OK: bundle/fonts/ already unpacked from {spec["asset"]}', file=sys.stderr)
        return 0

    if args.force or not verify(spec, path, quiet=True):
        download(spec, path)
        if not verify(spec, path):
            sys.exit('downloaded font bundle failed verification')
    print(f'OK: {spec["asset"]} verified ({os.path.getsize(path) / 1e6:.0f} MB)', file=sys.stderr)

    if args.extract:
        extract(spec, path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
