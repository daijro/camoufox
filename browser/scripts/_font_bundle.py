"""Shared by the font tools that read the extracted font bundle."""
import json
import os
import sys


def require_bundle(bundle):
    """Exit with the fix, not a stack trace, when the bundle is not extracted.

    `bundle` is either browser/bundle or browser/bundle/fonts.
    """
    fonts = bundle if bundle.rstrip('/').endswith('fonts') else os.path.join(bundle, 'fonts')
    if os.path.isdir(fonts) and os.listdir(fonts):
        return
    sys.exit(
        f'font bundle not present at {fonts}.\n'
        f'It ships as a release asset rather than repo content (~2.1 GB); run:\n'
        f'    make fonts-extract\n'
        f'See scripts/fetch-fonts.py for why it is not in git.'
    )


def read_groups(fonts):
    """(groups, readBy) from bundle/fonts/groups.json.

    The bundle stores each face once, in a directory named for the set of OSes
    that use it; readBy maps each OS to the groups it renders from.
    """
    path = os.path.join(fonts, 'groups.json')
    if not os.path.exists(path):
        sys.exit(f'{path} is missing: run `make fonts-extract`, or scripts/gen-font-groups.py '
                 f'after changing the bundle')
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    return data['groups'], data['readBy']
