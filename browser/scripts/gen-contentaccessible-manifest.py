#!/usr/bin/env python3
"""
Record which files a stock Firefox release exposes to web content.

Packages flagged `contentaccessible=yes` in chrome.manifest can be loaded as
subresources by any page, from any origin (caps/nsScriptSecurityManager.cpp
checks the target's flag and not the source), so any file Camoufox adds, drops
or renames there is page-detectable.

    python3 scripts/gen-contentaccessible-manifest.py /path/to/firefox

Writes scripts/data/contentaccessible-manifest.json, which
tests/playwright/patches/contentaccessible-parity.py diffs a build against. Re-run it on a
Firefox uplift; the guard refuses to compare across versions.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "scripts" / "data" / "contentaccessible-manifest.json"
JARS = ("browser/omni.ja", "omni.ja")


def zip_entries(jar: Path) -> dict:
    """Map member -> size. Uses unzip, not zipfile: Firefox's optimized jars
    have the central directory at the front and zipfile cannot open them."""
    out = subprocess.run(["unzip", "-l", str(jar)], capture_output=True, text=True).stdout
    entries = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and not parts[3].endswith("/"):
            entries[parts[3]] = int(parts[0])
    return entries


def zip_read(jar: Path, member: str) -> str:
    return subprocess.run(
        ["unzip", "-p", str(jar), member], capture_output=True
    ).stdout.decode("utf8", "replace")


def resolve(target: str, base: str) -> tuple:
    """A manifest target -> (jar, prefix). Most are relative to the manifest, but
    `resource` entries may name a resource:// URI, which lands elsewhere."""
    if target.startswith("resource://gre/"):
        return "omni.ja", target[len("resource://gre/"):]
    if target.startswith("resource://devtools/"):
        return "browser/omni.ja", "chrome/devtools/modules/devtools/" + target[len("resource://devtools/"):]
    return None, base + target


def packages(root: Path) -> dict:
    """{jar|kind|name: [jar-relative prefix, ...]} for every contentaccessible package."""
    found = {}
    for jar in JARS:
        path = root / jar
        if not path.exists():
            continue
        for member in [m for m in zip_entries(path) if m.endswith("chrome.manifest")]:
            base = member.rsplit("/", 1)[0] + "/" if "/" in member else ""
            for line in zip_read(path, member).splitlines():
                if "contentaccessible=yes" not in line:
                    continue
                kind, name, target = line.split()[:3]
                other_jar, prefix = resolve(target, base)
                found.setdefault(f"{other_jar or jar}|{kind}|{name}", set()).add(prefix)
    return {k: sorted(v) for k, v in found.items()}


def firefox_version(root: Path) -> str:
    ini = (root / "application.ini").read_text(errors="replace")
    match = re.search(r"^Version=(.+)$", ini, re.M)
    return match.group(1).strip() if match else "unknown"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    if root.is_file():
        root = root.parent
    if not (root / "application.ini").exists():
        print(f"FAIL: {root} is not a Firefox install (no application.ini)")
        return 1

    pkgs = packages(root)
    listings = {jar: zip_entries(root / jar) for jar in JARS if (root / jar).exists()}

    manifest = {"firefox_version": firefox_version(root), "packages": {}}
    total = 0
    for key, prefixes in sorted(pkgs.items()):
        jar = key.split("|", 1)[0]
        files = sorted(
            name for name in listings.get(jar, {})
            if any(name.startswith(p) for p in prefixes)
        )
        manifest["packages"][key] = {"prefixes": prefixes, "files": files}
        total += len(files)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"Firefox {manifest['firefox_version']}: {len(pkgs)} packages, {total} files")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
