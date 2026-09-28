#!/usr/bin/env python3
"""Release plumbing: prereleases on every merge, stable releases by tag.

Every merge to main that passes the test pipeline publishes a prerelease of
everything: a browser build if the browser's sources changed (a GitHub
prerelease with its own release number), then the Python package on PyPI and the
npm package under the `next` dist-tag. Pushing a `vX.Y.Z` tag on a tested main
commit promotes it: the browser release built from that commit's sources becomes
the stable, latest release, and X.Y.Z is published to PyPI and to npm `latest`.

Each library release is paired with exactly one browser release -- the one built
from the same sources, found by `ci.browser_inputs.source_digest()` -- and
`stamp` writes that pairing into the package (pythonlib/camoufox/browser-pin.json,
read by both launchers). A library therefore never runs a browser it was not
released with unless its user explicitly chooses another.

    python3 -m ci.release browser-plan          # build a new browser, or reuse one
    python3 -m ci.release cut --tag TAG          # the release commit and tag
    python3 -m ci.release paired                 # the browser release for this tree
    python3 -m ci.release lib-plan --channel prerelease|stable [--tag vX.Y.Z]
    python3 -m ci.release stamp --browser-tag T --py-version V --npm-version V
    python3 -m ci.release promote                # paired browser -> stable, latest
    python3 -m ci.release check-tested           # 'All tests passed' on HEAD
    python3 -m ci.release check-promotable --tag vX.Y.Z
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from ._util import REPO_ROOT, die, http_json, log, read_upstream_sh, run, set_output
from .browser_inputs import source_digest

PYPI_PROJECT = "camoufox"
NPM_PACKAGE = "@camoufox/camoufox"
PIN_FILE = REPO_ROOT / "pythonlib" / "camoufox" / "browser-pin.json"
PYPROJECT = REPO_ROOT / "pythonlib" / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "typescript" / "package.json"
TS_VERSION = REPO_ROOT / "typescript" / "src" / "__version__.ts"

# Written into every browser release's notes; how a library finds its browser.
DIGEST_MARKER = "camoufox-source-digest"
COMMIT_MARKER = "camoufox-source-commit"

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_BROWSER_TAG = re.compile(r"^v(?P<version>[^-]+)-(?P<prefix>[a-z]+)\.(?P<n>\d+)$")


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------

def release_tuple(version: str) -> Tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if not m:
        raise ValueError(f"not a release version: {version!r}")
    return int(m[1]), int(m[2]), int(m[3])


def stable_versions(versions: Iterable[str]) -> List[Tuple[int, int, int]]:
    out = []
    for v in versions:
        try:
            out.append(release_tuple(v))
        except ValueError:
            continue
    return out


def prerelease_numbers(base: str, pypi: Iterable[str], npm: Iterable[str]) -> List[int]:
    """Prerelease counters already used for `base`, on either registry."""
    found = []
    py = re.compile(rf"^{re.escape(base)}b(\d+)$")
    js = re.compile(rf"^{re.escape(base)}-beta\.(\d+)$")
    for v in pypi:
        if m := py.match(v):
            found.append(int(m[1]))
    for v in npm:
        if m := js.match(v):
            found.append(int(m[1]))
    return found


@dataclass(frozen=True)
class LibVersion:
    py: str
    npm: str
    dist_tag: str


def plan_prerelease(checked_in: str, pypi: Sequence[str], npm: Sequence[str]) -> LibVersion:
    """The next prerelease: of the checked-in version if it is unreleased, else of the next patch."""
    released = stable_versions(pypi) + stable_versions(npm)
    latest = max(released) if released else (0, 0, 0)
    base_t = release_tuple(checked_in)
    if base_t <= latest:
        base_t = (latest[0], latest[1], latest[2] + 1)
    base = ".".join(map(str, base_t))
    n = max(prerelease_numbers(base, pypi, npm), default=0) + 1
    return LibVersion(py=f"{base}b{n}", npm=f"{base}-beta.{n}", dist_tag="next")


def plan_stable(tag: str, pypi: Sequence[str], npm: Sequence[str]) -> LibVersion:
    m = STABLE_TAG.match(tag)
    if not m:
        raise ValueError(f"{tag!r} is not a release tag (vX.Y.Z)")
    version = f"{m[1]}.{m[2]}.{m[3]}"
    if version in pypi or version in npm:
        raise ValueError(f"{version} is already published")
    released = stable_versions(pypi) + stable_versions(npm)
    if released and release_tuple(version) <= max(released):
        raise ValueError(f"{version} is not newer than the latest release "
                         f"{'.'.join(map(str, max(released)))}")
    return LibVersion(py=version, npm=version, dist_tag="latest")


def next_browser_release(upstream_release: str, tags: Iterable[str]) -> str:
    """The first unused release number: never below upstream.sh's, never reused.

    Numbers are global across Firefox versions, as they always have been
    (beta.30 on 152.0.4, then beta.31 ...), so every tag counts.
    """
    m = re.match(r"^([a-z]+)\.(\d+)$", upstream_release)
    if not m:
        raise ValueError(f"cannot number releases after {upstream_release!r}")
    prefix, floor = m[1], int(m[2])
    used = [int(t["n"]) for t in (_BROWSER_TAG.match(x) for x in tags)
            if t and t["prefix"] == prefix]
    return f"{prefix}.{max([floor] + [u + 1 for u in used])}"


def marker(name: str, value: str) -> str:
    return f"<!-- {name}: {value} -->"


def read_marker(body: Optional[str], name: str) -> Optional[str]:
    m = re.search(rf"<!--\s*{re.escape(name)}:\s*(\S+)\s*-->", body or "")
    return m[1] if m else None


def paired_release(releases: Sequence[dict], digest: str) -> Optional[dict]:
    """The newest published browser release built from these sources."""
    for rel in releases:  # the API lists newest first
        if not rel.get("draft") and read_marker(rel.get("body"), DIGEST_MARKER) == digest:
            return rel
    return None


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _gh_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def github_releases(repo: str) -> List[dict]:
    out: List[dict] = []
    for page in range(1, 11):
        batch = http_json(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
                          headers=_gh_headers())
        out += batch
        if len(batch) < 100:
            break
    return out


def registry_versions() -> Tuple[List[str], List[str]]:
    import urllib.error

    def fetch(url: str, key: str) -> List[str]:
        try:
            return list(http_json(url).get(key, {}))
        except urllib.error.HTTPError as err:
            if err.code == 404:  # never published
                return []
            raise

    return (fetch(f"https://pypi.org/pypi/{PYPI_PROJECT}/json", "releases"),
            fetch(f"https://registry.npmjs.org/{NPM_PACKAGE.replace('/', '%2f')}", "versions"))


def checked_in_version() -> str:
    m = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    if not m:
        die("pythonlib/pyproject.toml has no version")
    return m[1]


def repo_name() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or "daijro/camoufox"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_browser_plan(_: argparse.Namespace) -> int:
    digest = source_digest()
    found = paired_release(github_releases(repo_name()), digest)
    set_output("digest", digest)
    if found:
        log(f"{found['tag_name']} was built from these sources; no browser build needed")
        set_output("build", "false")
        set_output("tag", found["tag_name"])
        return 0
    up = read_upstream_sh()
    tags = run(["git", "tag", "-l", "v*"], cwd=REPO_ROOT, check=True).stdout.split()
    release = next_browser_release(up["release"], tags)
    tag = f"v{up['version']}-{release}"
    log(f"browser sources changed: building {tag}")
    set_output("build", "true")
    set_output("tag", tag)
    set_output("release", release)
    return 0


def cmd_cut(args: argparse.Namespace) -> int:
    """The release commit, beside main: upstream.sh names this release's number.

    main is protected, so the number cannot be committed there; the tag points at
    a commit whose only difference from the tested main commit is that line, and
    rebuilding from the tag reproduces the release exactly.
    """
    m = _BROWSER_TAG.match(args.tag)
    if not m:
        die(f"{args.tag!r} is not a browser release tag")
    path = REPO_ROOT / "upstream.sh"
    text = re.sub(r"^release=.*$", f"release={m['prefix']}.{m['n']}", path.read_text(), flags=re.M)
    path.write_text(text)
    run(["git", "commit", "-q", "-m", f"Release {args.tag}", "upstream.sh"], cwd=REPO_ROOT, check=True)
    run(["git", "tag", args.tag], cwd=REPO_ROOT, check=True)
    run(["git", "push", "origin", f"refs/tags/{args.tag}"], cwd=REPO_ROOT, check=True)
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    """The markers every browser release carries, for `paired` to find it by."""
    print(marker(DIGEST_MARKER, args.digest))
    print(marker(COMMIT_MARKER, args.commit))
    return 0


def cmd_paired(_: argparse.Namespace) -> int:
    digest = source_digest()
    found = paired_release(github_releases(repo_name()), digest)
    if not found:
        die(f"no browser release was built from these sources (source digest {digest}). "
            "The browser build for this commit failed or has not finished; see the "
            "'Build and Release' workflow.")
    set_output("browser_tag", found["tag_name"])
    set_output("browser_prerelease", "true" if found.get("prerelease") else "false")
    return 0


def cmd_lib_plan(args: argparse.Namespace) -> int:
    pypi, npm = registry_versions()
    try:
        plan = (plan_prerelease(checked_in_version(), pypi, npm) if args.channel == "prerelease"
                else plan_stable(args.tag, pypi, npm))
    except ValueError as err:
        die(str(err))
    set_output("py_version", plan.py)
    set_output("npm_version", plan.npm)
    set_output("dist_tag", plan.dist_tag)
    return 0


def _require_tested(sha: str) -> None:
    """The test pipeline's required check passed on exactly this commit."""
    checks = http_json(
        f"https://api.github.com/repos/{repo_name()}/commits/{sha}/check-runs"
        "?check_name=All%20tests%20passed&per_page=100",
        headers=_gh_headers(),
    ).get("check_runs", [])
    if not any(c.get("conclusion") == "success" for c in checks):
        die(f"'All tests passed' has not passed on {sha[:10]}; nothing untested is released")


def _head() -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True).stdout.strip()


def cmd_check_tested(_: argparse.Namespace) -> int:
    _require_tested(_head())
    return 0


def cmd_check_promotable(args: argparse.Namespace) -> int:
    """A tag promotes only a main commit on which the test pipeline passed."""
    if not STABLE_TAG.match(args.tag):
        die(f"{args.tag!r} is not a release tag (vX.Y.Z); nothing to promote")
    sha = _head()
    if not run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=REPO_ROOT).ok:
        die(f"{args.tag} points at {sha[:10]}, which is not on main")
    _require_tested(sha)
    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    m = _BROWSER_TAG.match(args.browser_tag)
    if not m:
        die(f"{args.browser_tag!r} is not a browser release tag")
    PIN_FILE.write_text(json.dumps({
        "tag": args.browser_tag,
        "repo": repo_name(),
        "repo_name": "Official",
        "version": m["version"],
        "build": f"{m['prefix']}.{m['n']}",
    }, indent=2) + "\n")
    PYPROJECT.write_text(re.sub(r'^version = "[^"]+"', f'version = "{args.py_version}"',
                                PYPROJECT.read_text(), count=1, flags=re.M))
    pkg = json.loads(PACKAGE_JSON.read_text())
    pkg["version"] = args.npm_version
    PACKAGE_JSON.write_text(json.dumps(pkg, indent="\t") + "\n")
    TS_VERSION.write_text(re.sub(r'(LIBRARY_VERSION\s*=\s*")[^"]+(")', rf"\g<1>{args.npm_version}\g<2>",
                                 TS_VERSION.read_text(), count=1))
    log(f"stamped camoufox {args.py_version} / {NPM_PACKAGE} {args.npm_version} "
        f"with browser {args.browser_tag}")
    return 0


def cmd_promote(_: argparse.Namespace) -> int:
    digest = source_digest()
    found = paired_release(github_releases(repo_name()), digest)
    if not found:
        die(f"no browser release was built from these sources (source digest {digest})")
    tag = found["tag_name"]
    if found.get("prerelease"):
        run(["gh", "release", "edit", tag, "--repo", repo_name(), "--prerelease=false", "--latest"],
            cwd=REPO_ROOT, check=True)
        log(f"{tag} is now the stable, latest browser release")
    else:
        log(f"{tag} is already a stable release")
    set_output("browser_tag", tag)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("browser-plan").set_defaults(fn=cmd_browser_plan)
    p = sub.add_parser("cut"); p.add_argument("--tag", required=True); p.set_defaults(fn=cmd_cut)
    p = sub.add_parser("notes"); p.add_argument("--digest", required=True)
    p.add_argument("--commit", required=True); p.set_defaults(fn=cmd_notes)
    sub.add_parser("paired").set_defaults(fn=cmd_paired)
    p = sub.add_parser("lib-plan"); p.add_argument("--channel", choices=["prerelease", "stable"], required=True)
    p.add_argument("--tag"); p.set_defaults(fn=cmd_lib_plan)
    sub.add_parser("check-tested").set_defaults(fn=cmd_check_tested)
    p = sub.add_parser("check-promotable"); p.add_argument("--tag", required=True)
    p.set_defaults(fn=cmd_check_promotable)
    p = sub.add_parser("stamp"); p.add_argument("--browser-tag", required=True)
    p.add_argument("--py-version", required=True); p.add_argument("--npm-version", required=True)
    p.set_defaults(fn=cmd_stamp)
    sub.add_parser("promote").set_defaults(fn=cmd_promote)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
