#!/usr/bin/env python3
import re
import sys

# List of fixes needed based on the reject files
fixes = [
    # HeadlessWidget.cpp: line 112 -> 114, nsBaseWidget -> nsIWidget
    {
        'old': '@@ -112,6 +112,8 @@ void HeadlessWidget::Destroy() {\n     }\n   }\n \n+  SetSnapshotListener(nullptr);\n+\n   nsBaseWidget::OnDestroy();\n \n   nsBaseWidget::Destroy()',
        'new': '@@ -114,6 +114,8 @@ void HeadlessWidget::Destroy() {\n     }\n   }\n\n+  SetSnapshotListener(nullptr);\n+\n   nsIWidget::OnDestroy();\n\n   nsIWidget::Destroy()',
    },
]

patch_file = '/Users/jish/Documents/GitHub/camoufox/patches/playwright/0-playwright.patch'

with open(patch_file, 'r') as f:
    content = f.read()

for fix in fixes:
    if fix['old'] in content:
        content = content.replace(fix['old'], fix['new'])
        print(f"Applied fix")
    else:
        print(f"Fix not found - searching...")
        # Try to find similar content
        lines = fix['old'].split('\\n')
        for line in lines[:3]:
            if line and line in content:
                print(f"  Found part: {line[:50]}")

with open(patch_file, 'w') as f:
    f.write(content)

print("Done")
