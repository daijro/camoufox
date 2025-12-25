#!/usr/bin/env python3
"""Fix fingerprint-injection.patch line numbers for Firefox 146."""

import re
import sys

# Read the patch file
with open('/Users/jish/Documents/GitHub/camoufox/patches/fingerprint-injection.patch', 'r') as f:
    patch_content = f.read()

# Define the corrections needed based on analysis
# Format: (old_hunk_header, new_hunk_header)
corrections = [
    # Navigator.cpp - include section (line 8 vs 10 expected, -2 offset at start)
    (r'@@ -8,6 \+8,7 @@\n #include "base/basictypes\.h"\n \n #include "Navigator\.h"',
     '@@ -6,6 +8,7 @@\n /* file, You can obtain one at http://mozilla.org/MPL/2.0/. */\n \n // Needs to be first.\n #include "Navigator.h"\n+#include "MaskConfig.hpp"\n \n #include "Geolocation.h"\n #include "base/basictypes.h"'),

    # GetUserAgent (line 262 vs 267 expected, -5)
    (r'@@ -267,6 \+268,8 @@ void Navigator::Invalidate\(\)\n \n void Navigator::GetUserAgent',
     '@@ -262,6 +263,8 @@ void Navigator::Invalidate()\n \n void Navigator::GetUserAgent'),

    # GetAppCodeName (line 291 vs 293 expected, -2)
    (r'@@ -293,6 \+296,8 @@ void Navigator::GetUserAgent',
     '@@ -291,6 +294,8 @@ void Navigator::GetUserAgent'),

    # GetAppVersion (line 313 vs 314 expected, -1)
    (r'@@ -314,6 \+319,8 @@ void Navigator::GetAppCodeName',
     '@@ -313,6 +318,8 @@ void Navigator::GetAppCodeName'),

    # GetAppName (line 327 vs 325 expected, +2)
    (r'@@ -325,6 \+332,8 @@ void Navigator::GetAppVersion',
     '@@ -327,6 +334,8 @@ void Navigator::GetAppVersion'),

    # GetAcceptLanguages (line 349 vs 350 expected, -1)
    (r'@@ -350,6 \+359,15 @@ void Navigator::GetAcceptLanguages',
     '@@ -349,6 +358,15 @@ void Navigator::GetAcceptLanguages'),

    # GetLanguage (line 414 vs 400 expected, +14)
    (r'@@ -400,6 \+418,8 @@',
     '@@ -414,6 +432,8 @@'),

    # GetPlatform (line 443 vs 423 expected, +20)
    (r'@@ -423,6 \+443,8 @@ void Navigator::GetLanguages',
     '@@ -443,6 +463,8 @@ void Navigator::GetLanguages'),

    # GetOscpu (line 470 vs 449 expected, +21)
    (r'@@ -449,6 \+471,8 @@ void Navigator::GetPlatform',
     '@@ -470,6 +492,8 @@ void Navigator::GetPlatform'),

    # GetProduct (line 513 vs 488 expected, +25)
    (r'@@ -488,10 \+512,14 @@ void Navigator::GetVendor',
     '@@ -513,10 +537,14 @@ void Navigator::GetVendor'),

    # PdfViewerEnabled (line 547 vs 517 expected, +30)
    (r'@@ -517,7 \+545,11 @@',
     '@@ -547,7 +575,11 @@'),

    # CookieEnabled (line 576 vs 543 expected, +33)
    (r'@@ -543,6 \+575,9 @@',
     '@@ -576,6 +608,9 @@'),

    # OnLine (line 625 vs 589 expected, +36)
    (r'@@ -589,6 \+624,8 @@',
     '@@ -625,6 +660,8 @@'),

    # GetBuildID (line 642 vs 603 expected, +39)
    (r'@@ -603,6 \+640,8 @@',
     '@@ -642,6 +679,8 @@'),

    # GetDoNotTrack (line 702 vs 659 expected, +43)
    (r'@@ -659,6 \+698,8 @@',
     '@@ -702,6 +741,8 @@'),

    # GlobalPrivacyControl (line 710 vs 673 expected, +37)
    (r'@@ -673,6 \+714,9 @@',
     '@@ -710,6 +751,9 @@'),

    # HardwareConcurrency (line 724 vs 684 expected, +40)
    (r'@@ -684,6 \+728,8 @@',
     '@@ -724,6 +768,8 @@'),

    # MaxTouchPoints (line 926 vs 882 expected, +44)
    (r'@@ -882,6 \+928,8 @@',
     '@@ -926,6 +972,8 @@'),
]

# Apply corrections
modified_content = patch_content

# Actually, let me just manually rebuild the Navigator.cpp section
# since the context lines also need updating
print("Due to complexity, need to manually fix the Navigator.cpp hunks...")
print("Let me check what other files have issues...")

# Check for other files in rejects
reject_files = [
    'docshell/base/BrowsingContext.h',
    'docshell/base/CanonicalBrowsingContext.cpp',
    'docshell/base/nsDocShell.cpp',
    'dom/base/Navigator.h',
    'dom/base/nsContentUtils.cpp',
    'dom/base/nsContentUtils.h',
    'dom/base/nsDOMWindowUtils.cpp',
    'dom/base/nsDOMWindowUtils.h',
    'dom/geolocation/moz.build',
    'dom/media/systemservices/video_engine/desktop_capture_impl.cc',
    'dom/workers/RuntimeService.cpp',
    'js/src/vm/DateTime.cpp',
    'layout/style/GeckoBindings.h',
    'toolkit/components/resistfingerprinting/nsUserCharacteristics.cpp',
    'widget/InProcessCompositorWidget.cpp',
    'widget/gtk/nsFilePicker.cpp',
    'widget/headless/HeadlessWidget.cpp',
    'widget/nsGUIEventIPC.h',
]

print("\nFiles with rejects (need to check which patch they're from):")
for f in reject_files:
    print(f"  - {f}")
