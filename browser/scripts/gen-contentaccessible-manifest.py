#!/usr/bin/env python3
"""
Record which files a stock Firefox release exposes to web content.

Packages flagged `contentaccessible=yes` in chrome.manifest can be loaded as
subresources by any page, from any origin (caps/nsScriptSecurityManager.cpp
checks the target's flag and not the source), so any file Camoufox adds, drops,
renames or changes there is page-detectable. Each file is recorded with its
SHA-256.

It also records the name of every chrome package and resource host the
manifests register, contentaccessible or not. Content processes receive all of
them, and a page can tell a registered name from an absent one:
new Worker("chrome://<name>/...") returns for the first and throws for the
second. hCaptcha probes chrome://juggler this way.

    python3 scripts/gen-contentaccessible-manifest.py /path/to/firefox

Writes scripts/data/contentaccessible-manifest.json, which
tests/playwright/patches/contentaccessible-parity.py diffs a build against. Re-run it on a
Firefox uplift; the guard refuses to compare across versions.
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
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


def packaged_bytes(f: Path) -> bytes:
    """A file's bytes as the packager writes them into omni.ja: it strips the
    `#` comment lines of .ftl and .properties files (mozpack's
    MinifiedCommentStripped), which an unpackaged tree still carries."""
    data = f.read_bytes()
    if f.suffix in (".ftl", ".properties"):
        data = b"".join(l for l in data.splitlines(keepends=True) if not l.startswith(b"#"))
    return data


def tree_hashes(base: Path, prefixes: list) -> dict:
    """Member -> SHA-256 for the files under `prefixes` in an extracted jar or
    an unpackaged dist/bin tree, which lays resources out at the same paths."""
    out = {}
    for prefix in prefixes:
        top = base / prefix
        if top.is_dir():
            for f in top.rglob("*"):
                if f.is_file():
                    out[f.relative_to(base).as_posix()] = hashlib.sha256(packaged_bytes(f)).hexdigest()
    return out


def jar_hashes(jar: Path, prefixes: list) -> dict:
    """Member -> SHA-256 for the files under `prefixes` in a jar."""
    with tempfile.TemporaryDirectory() as tmp:
        # unzip warns, with a non-zero exit, about the front-loaded central
        # directory of every optimized jar, so completeness is checked instead.
        proc = subprocess.run(
            ["unzip", "-qo", str(jar), *[p + "*" for p in prefixes], "-d", tmp],
            capture_output=True, text=True,
        )
        hashes = tree_hashes(Path(tmp), prefixes)
        listed = {m for m in zip_entries(jar) if any(m.startswith(p) for p in prefixes)}
        if set(hashes) != listed:
            raise RuntimeError(f"unzip {jar} extracted {len(hashes)} of {len(listed)} files: {proc.stderr.strip()}")
        return hashes


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


def registrations(root: Path) -> dict:
    """{kind: [name, ...]}: every chrome package (by content, locale or skin line)
    and every resource host the manifests register.

    Read from the jars of a packaged build, else from the loose manifests of an
    unpackaged dist/bin, which hold the same lines.
    """
    texts = []
    for jar in JARS:
        path = root / jar
        if path.exists():
            texts += [zip_read(path, m) for m in zip_entries(path) if m.endswith(".manifest")]
        else:
            base = root / "browser" if jar == "browser/omni.ja" else root
            texts += [f.read_text(errors="replace") for f in base.rglob("*.manifest")]
    found = {"content": set(), "locale": set(), "skin": set(), "resource": set()}
    for text in texts:
        for line in text.splitlines():
            words = line.split()
            if len(words) >= 2 and words[0] in found:
                found[words[0]].add(words[1])
    return {kind: sorted(names) for kind, names in found.items()}


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

    manifest = {"firefox_version": firefox_version(root), "packages": {}, "registered": registrations(root)}
    total = 0
    for key, prefixes in sorted(pkgs.items()):
        files = jar_hashes(root / key.split("|", 1)[0], prefixes)
        manifest["packages"][key] = {"prefixes": prefixes, "files": files}
        total += len(files)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"Firefox {manifest['firefox_version']}: {len(pkgs)} packages, {total} files")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
