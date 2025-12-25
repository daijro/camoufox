#!/usr/bin/env python3
"""Fix Navigator.cpp patch hunks for Firefox 146."""

import re

# Read the current source file to understand the actual structure
with open('/Users/jish/Documents/GitHub/camoufox/camoufox-146.0.1-beta.25/dom/base/Navigator.cpp', 'r') as f:
    source_lines = f.readlines()

# Find actual line numbers for key functions
patterns = {
    'Navigator.h include': r'^#include "Navigator\.h"',
    'GetUserAgent': r'^void Navigator::GetUserAgent\(',
    'GetAppCodeName': r'^void Navigator::GetAppCodeName\(',
    'GetAppVersion': r'^void Navigator::GetAppVersion\(',
    'GetAppName': r'^void Navigator::GetAppName\(',
    'GetAcceptLanguages': r'^void Navigator::GetAcceptLanguages\(',
    'GetLanguage': r'^void Navigator::GetLanguage\(',
    'GetPlatform': r'^void Navigator::GetPlatform\(',
    'GetOscpu': r'^void Navigator::GetOscpu\(',
    'GetProduct': r'^void Navigator::GetProduct\(',
    'GetProductSub': r'^void Navigator::GetProductSub\(',
    'PdfViewerEnabled': r'^bool Navigator::PdfViewerEnabled\(',
    'CookieEnabled': r'^bool Navigator::CookieEnabled\(',
    'OnLine': r'^bool Navigator::OnLine\(',
    'GetBuildID': r'^void Navigator::GetBuildID\(',
    'GetDoNotTrack': r'^void Navigator::GetDoNotTrack\(',
    'GlobalPrivacyControl': r'^bool Navigator::GlobalPrivacyControl\(',
    'HardwareConcurrency': r'^uint64_t Navigator::HardwareConcurrency\(',
    'MaxTouchPoints': r'^uint32_t Navigator::MaxTouchPoints\(',
}

line_numbers = {}
for i, line in enumerate(source_lines, 1):
    for name, pattern in patterns.items():
        if re.match(pattern, line):
            line_numbers[name] = i
            print(f"{name}: line {i}")

print("\nExpected vs Actual:")
expected = {
    'Navigator.h include': 10,
    'GetUserAgent': 267,
    'GetAppCodeName': 293,
    'GetAppVersion': 314,
    'GetAppName': 325,
    'GetAcceptLanguages': 350,
    'GetLanguage': 400,
    'GetPlatform': 423,
    'GetOscpu': 449,
    'GetProduct': 488,
    'GetProductSub': 493,
    'PdfViewerEnabled': 517,
    'CookieEnabled': 543,
    'OnLine': 589,
    'GetBuildID': 603,
    'GetDoNotTrack': 659,
    'GlobalPrivacyControl': 673,
    'HardwareConcurrency': 684,
    'MaxTouchPoints': 882,
}

for name, exp_line in expected.items():
    act_line = line_numbers.get(name, '?')
    diff = act_line - exp_line if isinstance(act_line, int) else '?'
    print(f"{name}: expected {exp_line}, actual {act_line}, diff {diff}")
