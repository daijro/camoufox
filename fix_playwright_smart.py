#!/usr/bin/env python3
"""
Smarter script to fix 0-playwright.patch line numbers.
Handles multi-hunk rejects and uses better context matching.
"""

import re
import os
from pathlib import Path
from difflib import SequenceMatcher

SKIP_FILES = {
    'dom/base/Navigator.cpp',  # API conflict
    'dom/base/Navigator.h',     # API conflict
}

def parse_reject_file(rej_path):
    """Parse all hunks from a reject file"""
    with open(rej_path, 'r') as f:
        content = f.read()

    hunks = []
    current_hunk = []

    for line in content.split('\n'):
        if line.startswith('@@'):
            if current_hunk:
                hunks.append('\n'.join(current_hunk))
            current_hunk = [line]
        elif current_hunk:
            current_hunk.append(line)

    if current_hunk:
        hunks.append('\n'.join(current_hunk))

    return hunks

def parse_hunk(hunk_text):
    """Parse a single hunk"""
    lines = hunk_text.split('\n')
    header = lines[0]

    match = re.match(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$', header)
    if not match:
        return None

    # Extract context lines (non-modified lines around the change)
    context_before = []
    context_after = []
    changes = []

    in_changes = False
    for line in lines[1:]:
        if not line:
            continue
        if line.startswith(' '):
            if not in_changes and not changes:
                context_before.append(line[1:])
            elif in_changes:
                context_after.append(line[1:])
        elif line.startswith('+') or line.startswith('-'):
            in_changes = True
            changes.append(line)

    return {
        'old_line': int(match.group(1)),
        'old_count': int(match.group(2)),
        'new_line': int(match.group(3)),
        'new_count': int(match.group(4)),
        'context': match.group(5),
        'header': header,
        'context_before': context_before,
        'context_after': context_after,
        'changes': changes,
        'full_text': hunk_text
    }

def find_line_in_source(source_lines, context_lines, approximate=False):
    """Find where context appears in source file"""
    # Try exact match first
    for i in range(len(source_lines)):
        match = True
        for j, ctx in enumerate(context_lines[:5]):  # Check first 5 context lines
            if i + j >= len(source_lines):
                match = False
                break
            if ctx.strip():
                if ctx.strip() not in source_lines[i + j]:
                    match = False
                    break
        if match:
            return i + 1  # 1-indexed

    # Try approximate matching
    if approximate and context_lines:
        best_match = None
        best_ratio = 0
        search_text = ' '.join(c.strip() for c in context_lines[:5])

        for i in range(len(source_lines)):
            window = ' '.join(source_lines[i:min(i+10, len(source_lines))])
            ratio = SequenceMatcher(None, search_text, window).ratio()
            if ratio > best_ratio and ratio > 0.6:
                best_ratio = ratio
                best_match = i + 1

        if best_match:
            return best_match

    return None

def update_hunk_in_patch(patch_path, source_file, old_header, new_line, old_count, new_count, context_str):
    """Update a single hunk header in the patch file"""
    with open(patch_path, 'r') as f:
        content = f.read()

    # Find file section
    file_start = content.find(f'diff --git a/{source_file}')
    if file_start == -1:
        return False

    next_file = content.find('\ndiff --git', file_start + 1)
    if next_file == -1:
        section = content[file_start:]
        section_end = len(content)
    else:
        section = content[file_start:next_file]
        section_end = file_start + len(section)

    # Find and replace the old header
    header_pos = section.find(old_header)
    if header_pos == -1:
        return False

    new_header = f'@@ -{new_line},{old_count} +{new_line},{new_count} @@{context_str}'

    # Replace in full content
    abs_pos = file_start + header_pos
    content = content[:abs_pos] + content[abs_pos:].replace(old_header, new_header, 1)

    with open(patch_path, 'w') as f:
        f.write(content)

    return True

def main():
    print("🔍 Finding reject files...")
    build_dir = Path('camoufox-146.0.1-beta.25')

    rejects = []
    for rej in build_dir.rglob('*.rej'):
        source_file = str(rej.relative_to(build_dir)).replace('.rej', '')
        if source_file not in SKIP_FILES:
            rejects.append((source_file, rej))

    print(f"Found {len(rejects)} reject files\n")

    fixed = 0
    failed = 0

    for source_file, rej_path in rejects:
        print(f"\n📝 {source_file}")

        source_path = build_dir / source_file
        if not source_path.exists():
            print(f"  ⚠️  Source file not found")
            continue

        with open(source_path, 'r') as f:
            source_lines = f.readlines()

        hunks = parse_reject_file(rej_path)
        print(f"  Found {len(hunks)} failed hunk(s)")

        for i, hunk_text in enumerate(hunks):
            hunk = parse_hunk(hunk_text)
            if not hunk:
                print(f"    Hunk {i+1}: ❌ Could not parse")
                failed += 1
                continue

            # Try to find using context before changes
            search_context = hunk['context_before'] if hunk['context_before'] else hunk['context_after']
            if not search_context:
                # Use the header context text as fallback
                if hunk['context']:
                    search_context = [hunk['context'].strip()]

            correct_line = find_line_in_source(source_lines, search_context, approximate=True)

            if not correct_line:
                print(f"    Hunk {i+1} (line {hunk['old_line']}): ❌ Context not found")
                failed += 1
                continue

            if correct_line == hunk['old_line']:
                print(f"    Hunk {i+1} (line {hunk['old_line']}): ✓ Already correct")
                continue

            print(f"    Hunk {i+1}: 📍 {hunk['old_line']} → {correct_line}", end='')

            if update_hunk_in_patch('patches/playwright/0-playwright.patch',
                                   source_file,
                                   hunk['header'],
                                   correct_line,
                                   hunk['old_count'],
                                   hunk['new_count'],
                                   hunk['context']):
                print(" ✅")
                fixed += 1
            else:
                print(" ❌ Update failed")
                failed += 1

    print(f"\n{'='*60}")
    print(f"✅ Fixed: {fixed} hunks")
    print(f"❌ Failed: {failed} hunks")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
