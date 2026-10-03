#!/usr/bin/env python3
"""install gate: both packages, installed the way a user installs them.

Packs pythonlib and the npm package exactly as they would be published, installs
each into a clean environment with an empty cache, and runs the real
`camoufox fetch`: the browser, the addons, the GeoIP database and the fpgen
model, downloaded and put in place.

Every other suite runs from the source tree, so none of them sees this path.
That is how a release shipped an npm `fetch` that failed whenever the
temporary directory was on a different filesystem from the cache (tmpfs /tmp,
a Docker volume, a separate /home): the GeoIP archive was unpacked in /tmp and
renamed into the cache, which fails with EXDEV across filesystems.

So the gate puts TMPDIR on its own filesystem and refuses to run if it is not:
a gate that cannot reproduce the condition must not pass as if it had checked
it. And it pins the packages to a published browser first, as release.yml
stamps every package it publishes, so `fetch` installs what a user's would.

Run (the temporary directory must be a separate mount, e.g. a tmpfs):
    python3 -m ci.run_install --tmpdir /mnt/install-tmp
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from . import release, results
from ._util import RESULTS_DIR, REPO_ROOT, WORK_DIR, run

PYTHONLIB = REPO_ROOT / "pythonlib"
TYPESCRIPT = REPO_ROOT / "typescript"


def newest_browser_tag() -> str:
    """The newest published browser release, for a tree no release was built from."""
    for rel in release.github_releases(release.repo_name()):  # newest first
        if not rel.get("draft") and release._BROWSER_TAG.match(rel["tag_name"]):
            return rel["tag_name"]
    raise SystemExit("no published browser release to pin")


def pin(tag: str) -> None:
    """Pin the packages to `tag`, as release.yml stamps every published package.

    Unstamped, the pin is empty and `fetch` picks a release by its own rules,
    which no published package does.
    """
    m = release._BROWSER_TAG.match(tag)
    if not m:
        raise SystemExit(f"{tag!r} is not a browser release tag")
    release.PIN_FILE.write_text(json.dumps({
        "tag": tag,
        "repo": release.repo_name(),
        "repo_name": "Official",
        "version": m["version"],
        "build": f"{m['prefix']}.{m['n']}",
    }, indent=2) + "\n")


def same_filesystem(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def installed(cache: Path, tag: str) -> List[str]:
    """What a finished `camoufox fetch` must have left in its cache."""
    missing = []
    version = tag[1:]
    if not list(cache.glob(f"camoufox/browsers/*/{version}-*/")):
        missing.append(f"the pinned browser {tag} under camoufox/browsers/")
    if not list(cache.glob("camoufox/geoip/mmdb/*.mmdb")):
        missing.append("a GeoIP database under camoufox/geoip/mmdb/")
    leftovers = [p.name for p in cache.glob("camoufox/geoip/.download-*")]
    if leftovers:
        missing.append(f"no staging directories left in camoufox/geoip/ (found {leftovers})")
    return missing


def fetch(result: results.GateResult, name: str, cmd: List[str], cwd: Path, home: Path, tmpdir: Path,
          tag: str, timeout: int) -> bool:
    cache = home / "cache"
    cache.mkdir(parents=True)
    env: Dict[str, str] = {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(cache),
        "TMPDIR": str(tmpdir),
    }
    proc = run(cmd, cwd=cwd, env=env, timeout=timeout, tee=True)
    test = f"{name}::camoufox fetch"
    if not proc.ok:
        result.record(test, results.FAIL)
        result.note(f"{name}: `camoufox fetch` exited {proc.code}")
        return False
    missing = installed(cache, tag)
    if missing:
        result.record(test, results.FAIL)
        result.note(f"{name}: `camoufox fetch` exited 0 but left out: " + "; ".join(missing))
        return False
    result.record(test, results.PASS)
    return True


def python_package(result: results.GateResult, work: Path, tmpdir: Path, tag: str, timeout: int) -> bool:
    venv = work / "venv"
    if run([sys.executable, "-m", "venv", str(venv)]).code != 0:
        result.record("pythonlib::install", results.ERROR)
        return False
    python = venv / "bin" / "python"
    # A regular install of the package directory builds and installs the
    # wheel, as PyPI would serve it; -e would run from the source tree.
    if run([str(python), "-m", "pip", "install", "-q", f"{PYTHONLIB}[geoip]"], timeout=timeout,
           tee=True).code != 0:
        result.record("pythonlib::install", results.FAIL)
        return False
    result.record("pythonlib::install", results.PASS)
    return fetch(result, "pythonlib", [str(python), "-m", "camoufox", "fetch"], work, work / "home", tmpdir,
                 tag, timeout)


def npm_package(result: results.GateResult, work: Path, tmpdir: Path, tag: str, timeout: int) -> bool:
    pack_dir = work / "pack"
    pack_dir.mkdir(parents=True)
    # pnpm pack runs the package's own build, so the tarball is what npm would get.
    if run(["pnpm", "pack", "--pack-destination", str(pack_dir)], cwd=TYPESCRIPT, timeout=timeout,
           tee=True).code != 0:
        result.record("typescript::install", results.FAIL)
        return False
    tarballs = list(pack_dir.glob("*.tgz"))
    project = work / "project"
    project.mkdir()
    (project / "package.json").write_text('{"name": "install-check", "private": true}\n', encoding="utf-8")
    if len(tarballs) != 1 or run(["npm", "install", "--no-audit", "--no-fund", str(tarballs[0])], cwd=project,
                                 timeout=timeout, tee=True).code != 0:
        result.record("typescript::install", results.FAIL)
        return False
    result.record("typescript::install", results.PASS)
    return fetch(result, "typescript", ["npx", "--no-install", "camoufox", "fetch"], project, work / "home", tmpdir,
                 tag, timeout)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tmpdir", type=Path, required=True,
                        help="the temporary directory, on a different filesystem from the work directory")
    parser.add_argument("--browser-tag", help="the browser release to pin; default: the newest published")
    parser.add_argument("--work", type=Path, default=WORK_DIR / "install")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    result = results.GateResult(gate="install")
    shutil.rmtree(args.work, ignore_errors=True)
    args.work.mkdir(parents=True)
    args.tmpdir.mkdir(parents=True, exist_ok=True)

    if same_filesystem(args.tmpdir, args.work):
        result.note(
            f"{args.tmpdir} and {args.work} are on the same filesystem, so this run could not catch a "
            "rename across filesystems. Mount a tmpfs for --tmpdir."
        )
        result.finish(results.ERROR).save(args.results_dir)
        return 1

    tag = args.browser_tag or newest_browser_tag()
    result.note(f"packages pinned to {tag}")
    unstamped = release.PIN_FILE.read_text(encoding="utf-8")
    tmpdir = Path(tempfile.mkdtemp(dir=args.tmpdir))
    try:
        pin(tag)
        ok = python_package(result, args.work / "pythonlib", tmpdir, tag, args.timeout)
        ok = npm_package(result, args.work / "typescript", tmpdir, tag, args.timeout) and ok
    finally:
        release.PIN_FILE.write_text(unstamped, encoding="utf-8")
    result.finish(results.PASS if ok else results.FAIL).save(args.results_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
