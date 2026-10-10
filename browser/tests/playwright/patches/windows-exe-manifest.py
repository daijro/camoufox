r"""
Verify camoufox.exe embeds Firefox's application manifest.

config/rules.mk embeds $(srcdir)/<program>.manifest, and browser/app only has
firefox.exe.manifest, so --with-app-name=camoufox built a camoufox.exe with NO
manifest: no Windows 10 supportedOS GUID, no Common-Controls v6 / mozglue
side-by-side declaration, for the exe and every child process it launches.
patches/windows-exe-manifest.patch adds browser/app/camoufox.exe.manifest as a
byte-identical copy.

Static guard (runs on any host): the patch creates exactly the source tree's
firefox.exe.manifest; and when a Windows package is present in dist/, its
camoufox.exe contains the Windows 10 supportedOS GUID.

    python browser/tests/playwright/patches/windows-exe-manifest.py
"""

import sys
import zipfile
from pathlib import Path

BROWSER_ROOT = Path(__file__).resolve().parents[3]
WIN10_GUID = b"8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a"


def patch_content(patch: Path) -> bytes:
    lines = patch.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("+++ b/browser/app/camoufox.exe.manifest"))
    body = [l[1:] for l in lines[start + 2:] if l.startswith("+")]
    return ("\n".join(body) + "\n").encode()


def main() -> int:
    failures = []
    patch = BROWSER_ROOT / "patches/windows-exe-manifest.patch"
    if not patch.exists():
        failures.append("patches/windows-exe-manifest.patch is missing")
    else:
        added = patch_content(patch)
        sources = sorted(BROWSER_ROOT.glob("camoufox-*/browser/app/firefox.exe.manifest"))
        if sources:
            if added != sources[-1].read_bytes():
                failures.append(f"camoufox.exe.manifest differs from {sources[-1].relative_to(BROWSER_ROOT)}")
            print(f"  patch == {sources[-1].relative_to(BROWSER_ROOT)} : {added == sources[-1].read_bytes()}")
        if WIN10_GUID not in added:
            failures.append("the manifest does not declare Windows 10 supportedOS")

    packages = sorted((BROWSER_ROOT / "dist").glob("camoufox-*-win.*.zip"))
    if packages:
        with zipfile.ZipFile(packages[-1]) as z:
            exe = z.read("camoufox.exe")
        embedded = WIN10_GUID in exe
        print(f"  {packages[-1].name}: camoufox.exe embeds the manifest : {embedded}")
        if not embedded:
            failures.append(f"{packages[-1].name}: camoufox.exe has no embedded manifest")
    else:
        print("  (no Windows package in dist/ -- package check skipped)")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: camoufox.exe gets Firefox's application manifest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
