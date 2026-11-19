#!/usr/bin/env python3
"""
The Remote Settings collections that decide what a page can see, bundled as
dumps so the browser never polls Mozilla's servers (rule
no-background-traffic in ci/tribal-rules.yml).

Run after a Firefox version bump, then commit what it writes:
    python3 scripts/remote_settings.py pin
"""

import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PIN = os.path.join(HERE, 'data', 'remote-settings.json')
DUMPS = os.path.join(HERE, '..', 'additions', 'services', 'settings', 'dumps', 'main')
UPSTREAM = os.path.join(HERE, '..', 'upstream.sh')
SERVER = 'https://firefox.settings.services.mozilla.com/v1'
COLLECTIONS = (
    'bounce-tracking-protection-exceptions',
    'fingerprinting-protection-overrides',
    'partitioning-exempt-urls',
    'query-stripping',
    'tracking-protection-lists',
    'url-classifier-exceptions',
)
VERSION_TERM = re.compile(r'env\.version\|versionCompare\("(\d+)\.0a1"\) (>=|<=|<|>) 0')


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'camoufox-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def firefox_version():
    with open(UPSTREAM, encoding='utf-8') as fh:
        return re.search(r'^version=(\S+)', fh.read(), re.M).group(1)


def applies_to(record, major):
    """Evaluate the only filter these collections use. Anything else must stop
    the pin: guessing would ship a list this Firefox would not have chosen."""
    expression = record.get('filter_expression') or ''
    if not expression:
        return True
    terms = expression.split(' && ')
    if not all(VERSION_TERM.fullmatch(term) for term in terms):
        sys.exit(f'{record["id"]}: cannot evaluate filter {expression!r}')
    for term in terms:
        boundary, op = VERSION_TERM.fullmatch(term).groups()
        # X.0 is above X.0a1, and X.0 is the version a build reports.
        above = major >= int(boundary)
        if {'>=': not above, '>': not above, '<': above, '<=': above}[op]:
            return False
    return True


def pin():
    version = firefox_version()
    major = int(version.split('.')[0])
    attachments = json.loads(fetch(f'{SERVER}/'))['capabilities']['attachments']['base_url']
    shutil.rmtree(DUMPS, ignore_errors=True)
    os.makedirs(DUMPS)
    counts = {}
    for collection in COLLECTIONS:
        changeset = json.loads(
            fetch(f'{SERVER}/buckets/main/collections/{collection}/changeset?_expected=0')
        )
        # Attachments are megabytes per Firefox version, so only this version's
        # go in. The browser evaluates the filters of everything else itself.
        records = [
            r for r in changeset['changes'] if 'attachment' not in r or applies_to(r, major)
        ]
        with open(os.path.join(DUMPS, f'{collection}.json'), 'w', encoding='utf-8') as fh:
            json.dump({'data': records, 'timestamp': changeset['timestamp']}, fh, sort_keys=True)
        counts[collection] = len(records)
        for record in records:
            if 'attachment' not in record:
                continue
            body = fetch(attachments + record['attachment']['location'])
            if hashlib.sha256(body).hexdigest() != record['attachment']['hash']:
                sys.exit(f'{collection}/{record["id"]}: attachment hash mismatch')
            folder = os.path.join(DUMPS, collection)
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, record['id']), 'wb') as fh:
                fh.write(body)
            with open(os.path.join(folder, f'{record["id"]}.meta.json'), 'w', encoding='utf-8') as fh:
                json.dump(record, fh, sort_keys=True)
    with open(PIN, 'w', encoding='utf-8') as fh:
        json.dump({'firefox': version, 'collections': counts}, fh, indent=2)
        fh.write('\n')
    print(counts)


if __name__ == '__main__':
    if sys.argv[1:] != ['pin']:
        sys.exit(__doc__)
    pin()
