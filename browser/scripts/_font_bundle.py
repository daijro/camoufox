"""Shared by the font tools that read the extracted font bundle."""
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
