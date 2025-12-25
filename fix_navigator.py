#!/usr/bin/env python3
"""Fix all Navigator.cpp hunks by finding actual line numbers"""
import re
import subprocess

# Read the clean Firefox 146 Navigator.cpp
with open('camoufox-146.0.1-beta.25/dom/base/Navigator.cpp', 'r') as f:
    firefox_lines = f.readlines()

# Find line numbers for each function/marker in Firefox 146
def find_line(pattern):
    for i, line in enumerate(firefox_lines, 1):
        if pattern in line:
            return i
    return None

# Read the patch
with open('patches/fingerprint-injection.patch', 'r') as f:
    patch_content = f.read()

# Find and print all Navigator.cpp hunks with their context
hunks = re.findall(r'(@@ -(\d+),\d+ \+\d+,\d+ @@[^\n]*\n(?:[^\n]*\n){0,3})', patch_content)
for hunk_header, old_line in hunks[:10]:
    print(f"Line {old_line}: {hunk_header[:80]}")
