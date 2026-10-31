#!/usr/bin/env python3
"""
The PGO profile a build uses: the one Mozilla trained for the stock release of
the same Firefox, so Camoufox's unpatched code is optimized as stock's is.

Mozilla trains one profile per shippable platform (taskcluster kind
generate-profile) and builds the release with it. data/pgo-profiles.json pins
each one by Taskcluster task and sha256 for the Firefox in upstream.sh.

Run:
    python3 scripts/pgo.py pin            # after a Firefox version bump
    python3 scripts/pgo.py fetch linux x86_64
"""

import hashlib
import json
import os
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PIN = os.path.join(HERE, 'data', 'pgo-profiles.json')
TASKCLUSTER = 'https://firefox-ci-tc.services.mozilla.com/api'
ARTIFACT = 'public/build/profdata.tar.xz'
MEMBERS = ('merged.profdata', 'en-US.log')

# Mozilla's profile platform for each Camoufox target, as `use-pgo` assigns
# them in Firefox 158's taskcluster/kinds/build: Linux arm64 is built with the
# x86_64 Linux profile.
PROFILE_FOR = {
    ('linux', 'x86_64'): 'linux64',
    ('linux', 'arm64'): 'linux64',
    ('windows', 'x86_64'): 'win64',
    ('windows', 'i686'): 'win32',
    ('macos', 'x86_64'): 'macosx64',
    ('macos', 'arm64'): 'macosx64-aarch64',
}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_pin(version):
    with open(PIN, encoding='utf-8') as fh:
        pin = json.load(fh)
    if pin['firefox'] != version:
        sys.exit(f'{PIN} pins the profiles of Firefox {pin["firefox"]}, not {version}. '
                 f'Run: python3 scripts/pgo.py pin')
    return pin


def cache_dir():
    return os.path.join(os.environ.get('MOZBUILD_STATE_PATH', os.path.expanduser('~/.mozbuild')),
                        'camoufox-pgo')


def fetch(target, arch, version):
    """Directory holding merged.profdata and en-US.log for this target."""
    entry = load_pin(version)['profiles'][PROFILE_FOR[(target, arch)]]
    dest = os.path.join(cache_dir(), entry['sha256'])
    if all(os.path.isfile(os.path.join(dest, m)) for m in MEMBERS):
        return dest

    os.makedirs(cache_dir(), exist_ok=True)
    archive = dest + '.tar.xz'
    if not os.path.isfile(archive) or digest(archive) != entry['sha256']:
        url = f'{TASKCLUSTER}/queue/v1/task/{entry["task"]}/artifacts/{ARTIFACT}'
        print(f'fetching {url}', file=sys.stderr)
        with urllib.request.urlopen(url, timeout=300) as resp, open(archive + '.part', 'wb') as out:
            while block := resp.read(1 << 20):
                out.write(block)
        os.replace(archive + '.part', archive)
        if digest(archive) != entry['sha256']:
            os.remove(archive)
            sys.exit(f'{url}: sha256 is not the pinned {entry["sha256"]}')

    tmp = dest + '.part'
    os.makedirs(tmp, exist_ok=True)
    with tarfile.open(archive, 'r:xz') as tf:
        for name in MEMBERS:
            member = tf.getmember(name)
            if not member.isfile():
                sys.exit(f'{archive}: {name} is not a regular file')
            with tf.extractfile(member) as src, open(os.path.join(tmp, name), 'wb') as out:
                out.write(src.read())
    os.replace(tmp, dest)
    os.remove(archive)
    return dest


def _get_json(url):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def release_commit(version):
    """The commit Mozilla released this Firefox from, by its release tag."""
    tag = 'FIREFOX_' + version.replace('.', '_') + '_RELEASE'
    obj = _get_json(f'https://api.github.com/repos/mozilla-firefox/firefox/git/ref/tags/{tag}')['object']
    if obj['type'] == 'tag':
        obj = _get_json(obj['url'])['object']
    return obj['sha']


def pin(version):
    """Pin the profile of every platform for this Firefox, by the sha256 its
    task recorded in its chain of trust."""
    commit = release_commit(version)
    profiles = {}
    for platform in sorted(set(PROFILE_FOR.values())):
        index = f'gecko.v2.mozilla-release.revision.{commit}.firefox.{platform}-profile'
        task = _get_json(f'{TASKCLUSTER}/index/v1/task/{index}')['taskId']
        cot = _get_json(f'{TASKCLUSTER}/queue/v1/task/{task}/artifacts/public/chain-of-trust.json')
        profiles[platform] = {'task': task, 'sha256': cot['artifacts'][ARTIFACT]['sha256']}
    with open(PIN, 'w', encoding='utf-8') as fh:
        json.dump({'firefox': version, 'commit': commit, 'profiles': profiles}, fh, indent=2)
        fh.write('\n')
    print(f'pinned the profiles of Firefox {version} ({commit[:12]}) in {PIN}')


def upstream_version():
    with open(os.path.join(HERE, '..', 'upstream.sh'), encoding='utf-8') as fh:
        return next(line.split('=', 1)[1].strip() for line in fh if line.startswith('version='))


if __name__ == '__main__':
    if sys.argv[1:2] == ['pin']:
        pin(upstream_version())
    elif sys.argv[1:2] == ['fetch'] and len(sys.argv) == 4:
        print(fetch(sys.argv[2], sys.argv[3], upstream_version()))
    else:
        sys.exit(__doc__)
