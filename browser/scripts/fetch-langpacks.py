#!/usr/bin/env python3
"""Download the official Firefox language packs that scripts/package.py bakes into
every package as packaged locales (see scripts/inject-locales.py).

The XPIs are identical across platforms; the only platform-specific pack is
macOS's ja-JP-mac. They must match the Firefox base version exactly: string
keys change between releases, and a mismatched pack would localize some
content-exposed strings and leave others English.

Usage: scripts/fetch-langpacks.py <firefox-version>   e.g. 152.0.4
Writes bundle/langpacks/<locale>.xpi and bundle/langpacks/VERSION.
"""
import json, os, re, sys, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor

BASE = "https://archive.mozilla.org/pub/firefox/releases/{version}/{platform}/xpi/"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bundle", "langpacks")


def listing(version, platform):
    html = urllib.request.urlopen(BASE.format(version=version, platform=platform), timeout=60).read().decode()
    return sorted(set(re.findall(r">([A-Za-z-]+)\.xpi<", html)))


def fetch(version, platform, code):
    path = os.path.join(DEST, f"{code}.xpi")
    data = urllib.request.urlopen(BASE.format(version=version, platform=platform) + f"{code}.xpi", timeout=120).read()
    with open(path + ".part", "wb") as f:
        f.write(data)
    with zipfile.ZipFile(path + ".part") as z:
        manifest = json.loads(z.read("manifest.json"))
    gecko = manifest["browser_specific_settings"]["gecko"]
    major = version.split(".")[0]
    if not gecko["strict_min_version"].startswith(major + ".") or code not in manifest["languages"]:
        raise SystemExit(f"{code}: unexpected manifest {gecko} {list(manifest['languages'])}")
    os.replace(path + ".part", path)
    return code


def main():
    version = sys.argv[1]
    os.makedirs(DEST, exist_ok=True)
    jobs = [("linux-x86_64", c) for c in listing(version, "linux-x86_64") if c != "en-US"]
    jobs += [("mac", c) for c in listing(version, "mac") if c not in {j[1] for j in jobs} and c != "en-US"]
    with ThreadPoolExecutor(8) as pool:
        done = list(pool.map(lambda j: fetch(version, *j), jobs))
    with open(os.path.join(DEST, "VERSION"), "w") as f:
        f.write(version + "\n")
    print(f"{len(done)} language packs for Firefox {version} in {os.path.normpath(DEST)}")


if __name__ == "__main__":
    main()
