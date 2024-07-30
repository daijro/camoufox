#!/usr/bin/env python3

"""
Simple script to apply *.bootstrap patches
This was separated from the main patch script because its indended to run on docker build.

Run:
    python3 scripts/init-patch.py <version> <release>
"""

from patch import list_files, patch, enter_srcdir, leave_srcdir


def apply_bootstrap_patches():
    enter_srcdir()

    # Apply bootstraps first
    for patch_file in list_files('../patches', suffix='*.bootstrap'):
        patch(patch_file)

    leave_srcdir()


if __name__ == "__main__":
    apply_bootstrap_patches()
