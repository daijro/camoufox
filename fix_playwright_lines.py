#!/usr/bin/env python3
"""
Automatically fix line numbers in 0-playwright.patch by reading reject files
and finding the correct locations in Firefox 146 source files.
"""

import re
import os
import subprocess
from pathlib import Path

# Files to skip (have API conflicts or style changes)
SKIP_FILES = {
    'dom/base/Navigator.cpp',  # API conflict - GetAcceptLanguages
    'dom/base/Navigator.h',     # API conflict - GetAcceptLanguages header
}

# Hunks to drop in BrowsingContext.h (style changes only)
DROP_HUNKS = {
    'docshell/base/BrowsingContext.h': [
        '@@ -205,10 +205,10 @@',  # OrientationType namespace change
    ]
}

def find_reject_files():
    """Find all .rej files from 0-playwright patch"""
    build_dir = Path('camoufox-146.0.1-beta.25')
    rejects = []
    for rej in build_dir.rglob('*.rej'):
        rel_path = str(rej.relative_to(build_dir)).replace('.rej', '')
        if rel_path not in SKIP_FILES:
            rejects.append((rel_path, rej))
    return rejects

def read_reject_hunk(rej_file):
    """Read hunk from reject file"""
    with open(rej_file, 'r') as f:
        content = f.read()

    # Parse hunk header
    match = re.search(r'^@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$', content, re.MULTILINE)
    if not match:
        return None

    old_line = int(match.group(1))
    old_count = int(match.group(2))
    new_line = int(match.group(3))
    new_count = int(match.group(4))
    context = match.group(5)

    # Extract context lines to search for
    lines = content.split('\n')
    context_lines = []
    for line in lines[1:]:
        if line.startswith(' '):
            context_lines.append(line[1:])
        elif line.startswith('-'):
            context_lines.append(line[1:])
        if len(context_lines) >= 3:
            break

    return {
        'old_line': old_line,
        'old_count': old_count,
        'new_line': new_line,
        'new_count': new_count,
        'context': context,
        'context_lines': context_lines,
        'full_hunk': content
    }

def find_correct_line(source_file, context_lines):
    """Find where the context appears in the actual source file"""
    with open(f'camoufox-146.0.1-beta.25/{source_file}', 'r') as f:
        source = f.readlines()

    # Search for matching context
    for i in range(len(source)):
        match = True
        for j, ctx in enumerate(context_lines):
            if i + j >= len(source):
                match = False
                break
            if ctx.strip() and ctx.strip() not in source[i + j]:
                match = False
                break
        if match:
            return i + 1  # Line numbers are 1-indexed

    return None

def update_patch_hunk(patch_file, source_file, old_hunk_header, new_line):
    """Update hunk header in patch file with correct line number"""
    with open(patch_file, 'r') as f:
        content = f.read()

    # Find the hunk for this file
    file_section_start = content.find(f'diff --git a/{source_file}')
    if file_section_start == -1:
        return False

    # Find next file section
    next_diff = content.find('\ndiff --git', file_section_start + 1)
    if next_diff == -1:
        file_section = content[file_section_start:]
    else:
        file_section = content[file_section_start:next_diff]

    # Update the hunk header
    old_match = re.search(re.escape(old_hunk_header), file_section)
    if not old_match:
        print(f"  ⚠️  Could not find hunk header: {old_hunk_header}")
        return False

    # Parse old header
    match = re.search(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$', old_hunk_header)
    if not match:
        return False

    old_count = match.group(2)
    new_count = match.group(4)
    context_text = match.group(5)

    new_hunk_header = f'@@ -{new_line},{old_count} +{new_line},{new_count} @@{context_text}'

    content = content.replace(old_hunk_header, new_hunk_header, 1)

    with open(patch_file, 'w') as f:
        f.write(content)

    return True

def main():
    print("🔍 Finding reject files from 0-playwright.patch...")
    rejects = find_reject_files()
    print(f"Found {len(rejects)} reject files to process\n")

    fixed = 0
    skipped = 0
    failed = 0

    for source_file, rej_file in rejects:
        print(f"📝 Processing: {source_file}")

        hunk = read_reject_hunk(rej_file)
        if not hunk:
            print(f"  ❌ Could not parse reject file")
            failed += 1
            continue

        # Check if this hunk should be dropped
        if source_file in DROP_HUNKS:
            hunk_header = f"@@ -{hunk['old_line']},{hunk['old_count']} +{hunk['new_line']},{hunk['new_count']} @@"
            if hunk_header in DROP_HUNKS[source_file]:
                print(f"  ⏭️  Skipping (style change only)")
                skipped += 1
                continue

        correct_line = find_correct_line(source_file, hunk['context_lines'])
        if not correct_line:
            print(f"  ❌ Could not find context in source file")
            failed += 1
            continue

        if correct_line == hunk['old_line']:
            print(f"  ✓ Already correct at line {correct_line}")
            continue

        print(f"  📍 Found at line {correct_line} (was {hunk['old_line']})")

        old_hunk_header = f"@@ -{hunk['old_line']},{hunk['old_count']} +{hunk['new_line']},{hunk['new_count']} @@{hunk['context']}"

        if update_patch_hunk('patches/playwright/0-playwright.patch', source_file, old_hunk_header, correct_line):
            print(f"  ✅ Updated!")
            fixed += 1
        else:
            print(f"  ❌ Failed to update")
            failed += 1

    print(f"\n{'='*50}")
    print(f"✅ Fixed: {fixed}")
    print(f"⏭️  Skipped: {skipped}")
    print(f"❌ Failed: {failed}")
    print(f"{'='*50}")

if __name__ == '__main__':
    main()
