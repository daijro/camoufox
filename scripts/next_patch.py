#!/usr/bin/env python3

"""
Given a patch file, return the next patch file that will be executed.
Patches are applied in alphabetical order by basename.

Usage:
    python3 scripts/next_patch.py <patch_file>
"""

import os
import sys

from _mixin import list_patches


def get_next_patch(current_patch, patches_dir):
    """Get the next patch file after the given patch"""
    patches = list(list_patches(patches_dir))

    if not patches:
        return None

    # Normalize the current patch path
    current_patch = current_patch.replace('\\', '/')

    # Try to find the current patch in the list
    current_index = None
    for i, patch in enumerate(patches):
        if patch == current_patch:
            current_index = i
            break

    # If not found by full path, try matching by basename
    if current_index is None:
        current_basename = os.path.basename(current_patch)
        for i, patch in enumerate(patches):
            if os.path.basename(patch) == current_basename:
                current_index = i
                break

    if current_index is None:
        sys.stderr.write(f'error: patch file "{current_patch}" not found in patch list\n')
        return None

    # Check if there's a next patch
    if current_index + 1 < len(patches):
        return patches[current_index + 1]

    return None


def main():
    if len(sys.argv) != 2:
        sys.stderr.write('Usage: python3 scripts/next_patch.py <patch_file>\n')
        sys.exit(1)

    current_patch = sys.argv[1]

    # Determine patches directory based on current working directory
    # If we're in the Firefox source dir, use '../patches'
    # If we're in the camoufox root, use 'patches'
    if os.path.exists('../patches'):
        patches_dir = '../patches'
    elif os.path.exists('patches'):
        patches_dir = 'patches'
    else:
        sys.stderr.write('error: could not find patches directory\n')
        sys.exit(1)

    next_patch = get_next_patch(current_patch, patches_dir)

    if next_patch is None:
        if os.path.basename(current_patch) in [os.path.basename(p) for p in list_patches(patches_dir)]:
            print("no more patches left!")
            sys.exit(0)
        else:
            sys.exit(1)

    print(next_patch)
    sys.exit(0)


if __name__ == "__main__":
    main()

