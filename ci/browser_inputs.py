#!/usr/bin/env python3
"""Split the browser's inputs into what needs a compiler and what does not.

Juggler is mostly JavaScript, and JavaScript does not need libxul relinked. But
a full build is what every change to `additions/` used to cost: 24 minutes, of
which ccache reported 98.63% hits -- so almost none of it was compiling C++. It
was Rust, linking, and packaging, none of which a `.js` file affects.

The saving is real and the trap is sharp, so this module is deliberately small
and deliberately paranoid.

**The hash IS the classification.** There is no "did only JS change?" diff here,
because a diff answers the wrong question -- it compares against the pull
request's base, while what matters is whether the cached browser was built from
the same native sources. So: hash every input that can change compiled output.
If that hash matches a cached browser, the compiled half is identical *by
construction*, whatever the diff says, and the resources can simply be laid over
it.

**Two things it would be easy to get wrong, and how they are closed:**

  `additions/juggler/` is not all JavaScript. It also holds the screencast
  encoder and the remote-debugging pipe -- 5 .cpp, 5 .h, 2 .idl, 3
  components.conf, 4 moz.build -- which are compiled into libxul. Only the files
  `jar.mn` actually lists as packaged resources are treated as resources.
  Everything else, including anything with an extension nobody has thought about
  yet, counts as native and forces a build. Fail closed.

  The source-to-destination mapping is per-file, not a prefix rule. jar.mn maps
  `TargetRegistry.js` to `content/TargetRegistry.js` (a level added),
  `content/FrameTree.js` to `content/content/FrameTree.js` (preserved), and
  `content/JugglerFrameChild.sys.mjs` to `content/JugglerFrameChild.sys.mjs` (a
  level dropped). Two files in the same source directory land at different
  depths. Assuming a prefix would write one of them to the wrong path, leave the
  old copy in place, and run a browser with stale Juggler -- while every suite
  reported green, because the browser works fine, it is just not the one under
  review. So the mapping is read from jar.mn, never inferred.

  jar.mn itself is native: it decides both the mapping and what is packaged at
  all, so changing it must force a real build rather than a re-overlay.

Run:
    python3 -m ci.browser_inputs --digest        # the native-inputs hash
    python3 -m ci.browser_inputs --list          # what feeds that hash
    python3 -m ci.browser_inputs --resources     # source -> path in the dist
    python3 -m ci.browser_inputs --overlay DIR   # lay resources over a dist/bin
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# The same set `resolve` greps to decide whether the browser changed at all.
# Kept in step by ci/tests/test_ci.py, because a path that can change the binary
# and is not hashed here would be served a stale browser.
BROWSER_DIRS = ("patches", "additions", "settings", "assets", "scripts")
BROWSER_FILES = ("upstream.sh", "Makefile")

# Scripts under scripts/ that cannot change compiled output, and so must not
# invalidate a 665 MB cached browser.
#
# scripts/ holds the build machinery -- patch.py, copy-additions.sh, package.py
# -- so hashing the directory wholesale is the right default. It also holds
# tools that operate on the PYTHON package's data files and are never invoked
# by a build, and those cost an hour each time they are touched: editing
# clean-fingerprint-data.py, which rewrites pythonlib JSON, forced a full
# rebuild of a browser whose sources had not moved (measured 2026-09-17).
#
# Nothing is excluded on the grounds that it "looks unrelated". An entry here
# is checked by ci/tests/test_ci.py against the build's own entry points, so a
# script that IS reachable from a build cannot sit in this list: getting that
# wrong serves a stale binary to every suite downstream, which is far worse
# than an unnecessary rebuild.
NON_NATIVE_SCRIPTS = frozenset(
    {
        "scripts/clean-fingerprint-data.py",
        "scripts/cursor-demo.py",
    }
)

# Where a build can reach a script from. Used by the test above, not here.
BUILD_ENTRY_POINTS = (
    "Makefile",
    "multibuild.py",
    "scripts/patch.py",
    "scripts/package.py",
    "scripts/copy-additions.sh",
    "scripts/_mixin.py",
)

JUGGLER = Path("additions") / "juggler"
JAR_MN = JUGGLER / "jar.mn"

# `content/Helper.js (Helper.js)` -- destination first, source in parentheses.
_ENTRY = re.compile(r"^\s*(\S+)\s+\((\S+)\)\s*$")
# `% content juggler %content/` -- the chrome package this jar registers.
_PACKAGE = re.compile(r"^\s*%\s+content\s+(\S+)\s+%")


def jar_entries(root: Optional[Path] = None) -> Dict[str, str]:
    """{repo-relative source: path inside the built dist}, straight from jar.mn.

    The dist path is `chrome/<package>/<destination>` -- observed directly
    against a build: `content/Helper.js` in jar.mn is
    `dist/bin/chrome/juggler/content/Helper.js` on disk.
    """
    root = root or REPO_ROOT
    text = (root / JAR_MN).read_text(encoding="utf-8")
    package = "juggler"
    for line in text.splitlines():
        found = _PACKAGE.match(line)
        if found:
            package = found.group(1)
            break

    entries: Dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#") or line.lstrip().startswith("%"):
            continue
        found = _ENTRY.match(line)
        if not found:
            continue
        destination, source = found.group(1), found.group(2)
        entries[str(JUGGLER / source)] = f"chrome/{package}/{destination}"
    return entries


def resource_sources(root: Optional[Path] = None) -> set:
    """Repo-relative paths that are packaged as-is and never compiled."""
    return set(jar_entries(root))


def native_inputs(root: Optional[Path] = None) -> List[str]:
    """Every browser input that is not a packaged resource, sorted.

    Anything unrecognised lands here rather than being skipped: a new file type
    under additions/ forces a build until somebody decides otherwise, which is
    the safe direction to be wrong in.
    """
    root = root or REPO_ROOT
    resources = resource_sources(root)
    found: List[str] = []
    for name in BROWSER_DIRS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root))
            if rel not in resources and rel not in NON_NATIVE_SCRIPTS:
                found.append(rel)
    for name in BROWSER_FILES:
        if (root / name).is_file():
            found.append(name)
    return sorted(found)


def native_digest(root: Optional[Path] = None) -> str:
    """A hash of the compiled browser's inputs. Same hash, same binary."""
    root = root or REPO_ROOT
    digest = hashlib.sha256()
    for rel in native_inputs(root):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256((root / rel).read_bytes()).digest())
    return digest.hexdigest()[:32]


def source_inputs(root: Optional[Path] = None) -> List[str]:
    """Every file that goes into the browser, compiled or packaged, sorted."""
    root = root or REPO_ROOT
    return sorted(set(native_inputs(root)) | resource_sources(root))


def source_digest(root: Optional[Path] = None) -> str:
    """A hash of everything the browser is built from, except its release number.

    This is what pairs a library release with a browser release: two commits
    with the same source digest produce the same browser, so a library built
    from either may name that browser's release. The release number is left
    out because the release workflow writes it into the build's working tree
    from the release tag (ci/release.py set-build), and that must not make the
    browser look different from the main commit it was built from.
    """
    root = root or REPO_ROOT
    digest = hashlib.sha256()
    for rel in source_inputs(root):
        data = (root / rel).read_bytes()
        if rel == "upstream.sh":
            data = b"\n".join(
                line for line in data.splitlines() if not line.strip().startswith(b"release=")
            )
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()[:32]


def overlay(dist_bin: Path, root: Optional[Path] = None) -> List[str]:
    """Lay the current resources over an already-built dist/bin.

    Every entry is written, not just the changed ones: the set is then always
    exactly what jar.mn says, so a stale file cannot survive. (A resource
    *removed* from jar.mn is handled by jar.mn being a native input -- that
    forces a real build rather than an overlay.)
    """
    root = root or REPO_ROOT
    written = []
    for source, destination in sorted(jar_entries(root).items()):
        target = dist_bin / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / source, target)
        written.append(destination)
    return written


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--source-digest", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--resources", action="store_true")
    parser.add_argument("--overlay", type=Path, metavar="DIST_BIN")
    args = parser.parse_args(argv)

    if args.digest:
        print(native_digest())
    if args.source_digest:
        print(source_digest())
    if args.list:
        for rel in native_inputs():
            print(rel)
    if args.resources:
        for source, destination in sorted(jar_entries().items()):
            print(f"{source} -> {destination}")
    if args.overlay:
        written = overlay(args.overlay)
        print(f"overlaid {len(written)} resource(s) onto {args.overlay}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
