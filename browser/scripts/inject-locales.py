#!/usr/bin/env python3
"""Package Firefox locales into an app dir the way a Mozilla multi-locale build does.

A langpack add-on is NOT equivalent to a localized build: the parent process
pre-creates nsContentUtils' shared string bundles (dom.properties, HtmlForm,
...) at startup, before add-on langpacks register, and caches them for the
process lifetime -- so constraint-validation messages stay English under a
langpack while XML parse errors go localized (measured on stock 152.0.4). A
Mozilla fr repack localizes both. This script turns official langpack XPIs
into PACKAGED locales: resources go into omni.ja / browser/omni.ja, chrome
`locale` lines into their chrome.manifest, and the code into
res/multilocale.txt, which LocaleService reads once at startup -- so the
locale is selectable by intl.locale.requested before any bundle exists.

Usage: inject-locales.py --source-tree <firefox src> <app-resources-dir> <langpack.xpi> [...]
  app-resources-dir: dir holding omni.ja + browser/omni.ja
  (Linux/Windows: the install dir; macOS: Camoufox.app/Contents/Resources)
Skips the `branding` package so the build keeps its own branding.
"""
import json, os, sys, zipfile

SKIP_PACKAGES = {"branding"}
PLATFORM_FLAGS = {"macosx": "os=Darwin", "linux": "os=LikeUnix", "android": "os=Android", "win": "os=WINNT"}


def _mozpack(source_tree):
    """Mozilla's jar reader/writer: omni.ja is an *optimized* jar (central directory
    and preload index first) that Python's zipfile cannot read."""
    for rel in ("python/mozbuild", "python/mozboot", "third_party/python/six",
                "testing/mozbase/mozfile", "third_party/python/looseversion"):
        sys.path.insert(0, os.path.join(source_tree, rel))
    from mozpack.mozjar import JarReader, JarWriter
    return JarReader, JarWriter


def rewrite_jar(mozpack, path, add_files, manifest_lines, locales_txt=None):
    """Rebuild a jar with extra entries, appended chrome/chrome.manifest lines and an
    optional res/multilocale.txt, keeping the original compression and preload order."""
    JarReader, JarWriter = mozpack
    reader = JarReader(path)
    names = list(reader.entries)
    if manifest_lines and "chrome/chrome.manifest" not in reader.entries:
        raise SystemExit(f"{path}: no chrome/chrome.manifest to register locales in")
    preloaded = []
    if reader.last_preloaded:
        preloaded = names[:names.index(reader.last_preloaded) + 1]
    tmp = path + ".tmp"
    with JarWriter(tmp, compress_level=9) as writer:
        for name in names:
            if name in add_files:
                continue  # replaced below
            entry = reader[name]
            data = entry.read()
            if name == "chrome/chrome.manifest" and manifest_lines:
                text = data.decode()
                if not text.endswith("\n"):
                    text += "\n"
                have = set(text.splitlines())
                data = (text + "".join(l + "\n" for l in manifest_lines if l not in have)).encode()
            elif name == "res/multilocale.txt" and locales_txt is not None:
                data = (locales_txt + "\n").encode()
            writer.add(name, data, compress=entry.compressed)
        if locales_txt is not None and "res/multilocale.txt" not in reader.entries:
            writer.add("res/multilocale.txt", (locales_txt + "\n").encode())
        for name, data in sorted(add_files.items()):
            writer.add(name, data)
        if preloaded:
            writer.preload(preloaded)
    os.replace(tmp, path)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Package Firefox locales from language packs")
    parser.add_argument("--source-tree", required=True, help="Firefox source tree (for mozpack)")
    parser.add_argument("res_dir", help="dir holding omni.ja and browser/omni.ja")
    parser.add_argument("xpis", nargs="+", help="official language pack XPIs")
    args = parser.parse_args()
    mozpack = _mozpack(args.source_tree)
    JarReader = mozpack[0]
    res_dir, xpis = args.res_dir, args.xpis
    gre_jar = os.path.join(res_dir, "omni.ja")
    app_jar = os.path.join(res_dir, "browser", "omni.ja")
    locales = [l.strip() for l in JarReader(gre_jar)["res/multilocale.txt"].read().decode().split(",") if l.strip()]
    gre_files, app_files, gre_lines, app_lines = {}, {}, [], []
    for xpi in xpis:
        with zipfile.ZipFile(xpi) as z:
            manifest = json.loads(z.read("manifest.json"))
            (code, lang), = manifest["languages"].items()
            for pkg, target in lang["chrome_resources"].items():
                if pkg in SKIP_PACKAGES:
                    continue
                for platform, rel in (target.items() if isinstance(target, dict) else [(None, target)]):
                    # xpi paths: chrome/... -> GRE jar chrome/...; browser/chrome/... -> app jar chrome/...
                    if rel.startswith("browser/chrome/"):
                        line, lines = f"locale {pkg} {code} {rel[len('browser/chrome/'):]}", app_lines
                    elif rel.startswith("chrome/"):
                        line, lines = f"locale {pkg} {code} {rel[len('chrome/'):]}", gre_lines
                    else:
                        raise SystemExit(f"{xpi}: unexpected chrome path {rel}")
                    if platform:
                        line += " " + PLATFORM_FLAGS[platform]
                    lines.append(line)
            for name in z.namelist():
                if name.endswith("/") or name == "manifest.json" or name.startswith("META-INF/"):
                    continue
                if "/locale/branding/" in name:
                    continue
                if name.startswith("browser/"):
                    app_files[name[len("browser/"):]] = z.read(name)
                else:
                    gre_files[name] = z.read(name)
            if code not in locales:
                locales.append(code)
            print(f"  {code}: {manifest['version']}")
    rewrite_jar(mozpack, gre_jar, gre_files, gre_lines, ",".join(locales))
    rewrite_jar(mozpack, app_jar, app_files, app_lines)
    print(f"packaged locales: {','.join(locales)}  (gre +{len(gre_files)} files, app +{len(app_files)} files)")


if __name__ == "__main__":
    main()
