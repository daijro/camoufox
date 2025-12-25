#!/usr/bin/env python3
"""
Comprehensive script to fix all patch hunks for Firefox 146.
This will analyze each reject and update the corresponding patch file.
"""

import os
import re
import subprocess

CAMOUFOX_DIR = '/Users/jish/Documents/GitHub/camoufox'
FIREFOX_DIR = f'{CAMOUFOX_DIR}/camoufox-146.0.1-beta.25'
PATCHES_DIR = f'{CAMOUFOX_DIR}/patches'

# Map of reject files to their source patch files
REJECT_TO_PATCH = {
    'browser/components/urlbar/UrlbarProviderInterventions.sys.mjs': 'no-search-engines.patch',
    'docshell/base/BrowsingContext.h': 'playwright/0-playwright.patch',
    'docshell/base/CanonicalBrowsingContext.cpp': 'playwright/0-playwright.patch',
    'docshell/base/nsDocShell.cpp': 'playwright/0-playwright.patch',
    'dom/base/Navigator.cpp': 'fingerprint-injection.patch',
    'dom/base/Navigator.h': 'fingerprint-injection.patch',
    'dom/base/nsContentUtils.cpp': 'playwright/0-playwright.patch',
    'dom/base/nsContentUtils.h': 'playwright/0-playwright.patch',
    'dom/base/nsDOMWindowUtils.cpp': 'playwright/0-playwright.patch',
    'dom/base/nsDOMWindowUtils.h': 'playwright/0-playwright.patch',
    'dom/geolocation/moz.build': 'geolocation-spoofing.patch',
    'dom/media/systemservices/video_engine/desktop_capture_impl.cc': 'screen-hijacker.patch',
    'dom/workers/RuntimeService.cpp': 'playwright/0-playwright.patch',
    'js/src/vm/DateTime.cpp': 'playwright/0-playwright.patch',
    'layout/style/GeckoBindings.h': 'screen-hijacker.patch',
    'toolkit/components/resistfingerprinting/nsUserCharacteristics.cpp': 'playwright/0-playwright.patch',
    'widget/InProcessCompositorWidget.cpp': 'screen-hijacker.patch',
    'widget/gtk/nsFilePicker.cpp': 'screen-hijacker.patch',
    'widget/headless/HeadlessWidget.cpp': 'screen-hijacker.patch',
    'widget/nsGUIEventIPC.h': 'playwright/0-playwright.patch',
}

def find_rejects():
    """Find all .rej files."""
    result = subprocess.run(
        ['find', FIREFOX_DIR, '-name', '*.rej', '-type', 'f'],
        capture_output=True, text=True
    )
    rejects = [r.replace(FIREFOX_DIR + '/', '') for r in result.stdout.strip().split('\n') if r]
    return rejects

def main():
    rejects = find_rejects()
    print(f"Found {len(rejects)} reject files:")

    patch_groups = {}
    for rej in rejects:
        base_file = rej.replace('.rej', '')
        patch = REJECT_TO_PATCH.get(base_file, 'UNKNOWN')
        if patch not in patch_groups:
            patch_groups[patch] = []
        patch_groups[patch].append(rej)
        print(f"  {rej} -> {patch}")

    print("\n=== Summary by patch ===")
    for patch, files in sorted(patch_groups.items()):
        print(f"\n{patch}: {len(files)} rejects")
        for f in files:
            print(f"  - {f}")

if __name__ == '__main__':
    main()
