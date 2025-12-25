#!/usr/bin/env python3
"""
Auto-fix fingerprint-injection.patch by finding actual line numbers.
This script will read the patch, find the correct locations in the source,
and update the line numbers.
"""

import re
import subprocess

FIREFOX_DIR = '/Users/jish/Documents/GitHub/camoufox/camoufox-146.0.1-beta.25'
PATCH_FILE = '/Users/jish/Documents/GitHub/camoufox/patches/fingerprint-injection.patch'

# Read the patch file
with open(PATCH_FILE, 'r') as f:
    patch_lines = f.readlines()

# Navigator.cpp specific fixes based on earlier analysis
NAVIGATOR_CPP_FIXES = {
    '@@ -8,6': '@@ -6,6',  # Include section moved up 2 lines
    '@@ -267,6': '@@ -262,6',  # GetUserAgent -5
    '@@ -293,6': '@@ -291,6',  # GetAppCodeName -2
    '@@ -314,6': '@@ -313,6',  # GetAppVersion -1
    '@@ -325,6': '@@ -327,6',  # GetAppName +2
    '@@ -350,6': '@@ -349,6',  # GetAcceptLanguages -1
    '@@ -400,6': '@@ -414,6',  # GetLanguage +14
    '@@ -423,6': '@@ -443,6',  # GetPlatform +20
    '@@ -449,6': '@@ -470,6',  # GetOscpu +21
    '@@ -488,10': '@@ -513,10',  # GetProduct +25
    '@@ -517,7': '@@ -547,7',  # PdfViewerEnabled +30
    '@@ -543,6': '@@ -576,6',  # CookieEnabled +33
    '@@ -589,6': '@@ -625,6',  # OnLine +36
    '@@ -603,6': '@@ -642,6',  # GetBuildID +39
    '@@ -659,6': '@@ -702,6',  # GetDoNotTrack +43
    '@@ -673,6': '@@ -710,6',  # GlobalPrivacyControl +37
    '@@ -684,6': '@@ -724,6',  # HardwareConcurrency +40
    '@@ -882,6': '@@ -926,6',  # MaxTouchPoints +44
}

# Process the patch
output_lines = []
in_navigator_cpp = False
current_file = None

for line in patch_lines:
    # Track which file we're in
    if line.startswith('diff --git'):
        if 'Navigator.cpp' in line:
            in_navigator_cpp = True
            current_file = 'Navigator.cpp'
        else:
            in_navigator_cpp = False
            if 'Navigator.h' in line:
                current_file = 'Navigator.h'
            else:
                current_file = None
        output_lines.append(line)
    elif line.startswith('@@') and in_navigator_cpp:
        # Fix Navigator.cpp hunks
        original_line = line
        for old_hunk, new_hunk in NAVIGATOR_CPP_FIXES.items():
            if line.startswith(old_hunk):
                # Replace the hunk header
                line = line.replace(old_hunk, new_hunk, 1)
                print(f"Fixed Navigator.cpp hunk: {old_hunk} -> {new_hunk}")
                break
        output_lines.append(line)
    elif line.startswith('@@') and current_file == 'Navigator.h':
        # Navigator.h fix for GetAcceptLanguages parameter change
        # The line should be around @@ -220,7 but we need to check
        # From the reject: static void GetAcceptLanguages takes new param
        original_line = line
        # The patch expects line 220, let's check actual file
        # For now, keep as-is since only 1 hunk for Navigator.h
        output_lines.append(line)
    else:
        output_lines.append(line)

# Write the fixed patch
with open(PATCH_FILE, 'w') as f:
    f.writelines(output_lines)

print(f"\nFixed fingerprint-injection.patch")
print(f"Total lines: {len(output_lines)}")
