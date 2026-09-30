#!/usr/bin/env python3
"""Release plumbing for .github/workflows/release.yml.

Every merge to main that passes the test pipeline publishes a prerelease: a
browser build if the browser's sources changed (a GitHub prerelease with its own
release number), then -- if the library changed -- the Python package on PyPI and
the npm package under the `next` dist-tag. Pushing a `vX.Y.Z` tag on a tested main
commit promotes it: the browser release built from that commit's sources becomes
the stable, latest release, and X.Y.Z is published to PyPI and to npm `latest`.

Each library release is paired with exactly one browser release -- the one built
from the same sources, found by `ci.browser_inputs.source_digest()` in the
release's manifest.json asset -- and `stamp` writes that pairing into the package
(pythonlib/camoufox/browser-pin.json, read by both launchers). A library therefore
never runs a browser it was not released with unless its user explicitly chooses
another.

A browser release's number is not committed anywhere: its tag points at the
tested main commit, and `set-build` writes the number from the tag name into the
build's working tree. Rebuilding from the tag with `set-build` reproduces it.

    python3 -m ci.release browser-plan           # build a new browser, or reuse one
    python3 -m ci.release set-build --tag TAG     # upstream.sh names TAG's number (working tree only)
    python3 -m ci.release manifest --tag T --digest D --commit C   # the release's manifest.json
    python3 -m ci.release paired [--root DIR] [--releases JSON]  # the browser release for this tree
    python3 -m ci.release lib-plan --channel prerelease|stable [--tag vX.Y.Z]
    python3 -m ci.release stamp --browser-tag T --py-version V --npm-version V
    python3 -m ci.release lib-diff --channel C --wheel W --tarball T --py-version V --npm-version V
    python3 -m ci.release promote                 # paired browser -> stable, latest
    python3 -m ci.release check-promotable --tag vX.Y.Z
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from ._util import REPO_ROOT, die, http_json, log, read_upstream_sh, run, set_output
from .browser_inputs import BROWSER_DIRS, BROWSER_FILES, NON_NATIVE_SCRIPTS, source_digest

PYPI_PROJECT = "camoufox"
NPM_PACKAGE = "@camoufox/camoufox"
PIN_FILE = REPO_ROOT / "pythonlib" / "camoufox" / "browser-pin.json"
PYPROJECT = REPO_ROOT / "pythonlib" / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "typescript" / "package.json"
TS_VERSION = REPO_ROOT / "typescript" / "src" / "__version__.ts"

# Attached to every browser release; how a library finds its browser.
MANIFEST_ASSET = "manifest.json"

# The one check the test pipeline reports. Run by release.yml it is named
# "tests / All tests passed"; run on a pull request, "All tests passed".
GATE_CHECK = "All tests passed"

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
# Every published library version is tagged: vX.Y.Z, or vX.Y.ZbN for a
# prerelease (PEP 440 spelling, so it never reads as a browser tag).
LIBRARY_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:b(\d+))?$")
# What a library release ships besides the browser it pairs with.
LIBRARY_DIRS = ("pythonlib", "typescript")
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


def manifest(tag: str, digest: str, commit: str) -> dict:
    """What every browser release carries as its manifest.json asset."""
    return {"schema": 1, "tag": tag, "source_digest": digest, "commit": commit}


def release_manifest(rel: dict) -> Optional[dict]:
    """A release's manifest.json, or None for a release published without one.

    A release dict may carry it pre-fetched under "manifest" (the tests do);
    otherwise the asset is downloaded. The repository is public, so no token is
    sent -- the download redirects to a host that must not receive it.
    """
    if "manifest" in rel:
        return rel["manifest"]
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == MANIFEST_ASSET), None)
    if asset is None:
        return None
    return http_json(asset["browser_download_url"])


def paired_release(releases: Sequence[dict], digest: str) -> Optional[dict]:
    """The newest published browser release built from these sources."""
    for rel in releases:  # the API lists newest first
        if rel.get("draft"):
            continue
        found = release_manifest(rel)
        if found and found.get("source_digest") == digest:
            return rel
    return None


def library_version_key(tag: str) -> Optional[Tuple[int, int, int, float]]:
    """Version order for a library tag: 0.5.7b1 < 0.5.7b2 < 0.5.7 < 0.5.8b1."""
    m = LIBRARY_TAG.match(tag)
    if not m:
        return None
    return int(m[1]), int(m[2]), int(m[3]), float(m[4]) if m[4] else float("inf")


def last_library_tag(tags: Iterable[str]) -> Optional[str]:
    keyed = [(k, t) for t in tags if (k := library_version_key(t))]
    return max(keyed)[1] if keyed else None


def is_library_source(rel: str) -> bool:
    """Whether a change to `rel` changes what a library release would ship."""
    return rel.split("/", 1)[0] in LIBRARY_DIRS or is_browser_source(rel)


def is_browser_source(rel: str) -> bool:
    """Whether a repo-relative path goes into the browser (as source_digest counts it)."""
    if rel in NON_NATIVE_SCRIPTS:
        return False
    return rel in BROWSER_FILES or rel.split("/", 1)[0] in BROWSER_DIRS


@dataclass(frozen=True)
class Pairing:
    release: Optional[dict]
    why: str
    ahead: Tuple[str, ...] = ()


def find_paired(releases: Sequence[dict], root: Path = REPO_ROOT) -> Pairing:
    """The published browser release built from the sources at `root`, and why.

    A release built by release.yml carries its source digest in its manifest.json,
    and a match there is exact. Releases cut before the manifest existed (up to and
    including v156.0.1-beta.32) are found the way tests.yml used to find them:
    the tag upstream.sh names, published, with no browser source changed since.
    Anything else -- a draft, a tag that was never released, or a base branch
    whose browser sources moved past every release -- pairs with nothing, and
    the caller builds.
    """
    digest = source_digest(root)
    found = paired_release(releases, digest)
    if found:
        return Pairing(found, f"{found['tag_name']} carries source digest {digest}")

    up = read_upstream_sh(root / "upstream.sh")
    tag = f"v{up['version']}-{up['release']}"
    rel = next((r for r in releases if r.get("tag_name") == tag), None)
    if rel is None or rel.get("draft"):
        return Pairing(None, f"no published release {tag}, and none carries source digest {digest}")
    if not run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=root).ok:
        return Pairing(None, f"release {tag} is published but its tag is not in this checkout")
    diff = run(["git", "diff", "--name-only", tag, "HEAD"], cwd=root, check=True).stdout.split()
    ahead = tuple(sorted(f for f in diff if is_browser_source(f)))
    if ahead:
        return Pairing(None, f"the browser sources differ from {tag} in {len(ahead)} files", ahead)
    return Pairing(rel, f"no browser source differs from {tag}")


# ---------------------------------------------------------------------------
# is a built package new?
# ---------------------------------------------------------------------------

_PY_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:b(\d+))?$")
_NPM_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")


def newest_version(versions: Iterable[str], spelling: "re.Pattern[str]") -> Optional[str]:
    """The highest version in `spelling` (PyPI's or npm's), a prerelease below its release.

    Versions in any other form are ignored: this package has never published one,
    and guessing how one orders is worse than leaving it out.
    """
    keyed = []
    for v in versions:
        if m := spelling.match(v):
            keyed.append(((int(m[1]), int(m[2]), int(m[3]), float(m[4]) if m[4] else float("inf")), v))
    return max(keyed)[1] if keyed else None


def package_files(path: Path, version: str) -> dict:
    """{name: bytes} for a wheel or an npm tarball, with its own version taken out.

    What is compared is what a user installs, so the version -- which every
    release changes -- is replaced by a placeholder wherever it appears (the
    dist-info directory, METADATA, package.json, the version module), and the
    wheel's RECORD, which only hashes the other files, is left out.
    """
    import tarfile
    import zipfile

    files: dict = {}
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.endswith("/"):
                    files[name] = z.read(name)
    else:
        with tarfile.open(path) as t:
            for member in t.getmembers():
                if member.isfile():
                    files[member.name] = t.extractfile(member).read()
    old = version.encode()
    out = {}
    for name, data in files.items():
        name = name.replace(version, "@VERSION@")
        if name.endswith(".dist-info/RECORD"):
            continue
        out[name] = data.replace(old, b"@VERSION@")
    return out


def package_diff(built: dict, published: dict) -> List[str]:
    """Names that differ between two package_files() results, sorted."""
    return sorted(n for n in set(built) | set(published) if built.get(n) != published.get(n))


def _download(url: str, dest: Path) -> Path:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "camoufox-harness"})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        dest.write_bytes(resp.read())
    return dest


def published_wheel(version: str, dest: Path) -> Path:
    urls = http_json(f"https://pypi.org/pypi/{PYPI_PROJECT}/{version}/json")["urls"]
    wheels = [u for u in urls if u.get("packagetype") == "bdist_wheel"]
    if len(wheels) != 1:
        die(f"{PYPI_PROJECT} {version} has {len(wheels)} wheels on PyPI; expected one")
    return _download(wheels[0]["url"], dest / wheels[0]["filename"])


def published_tarball(version: str, dest: Path) -> Path:
    meta = http_json(f"https://registry.npmjs.org/{NPM_PACKAGE.replace('/', '%2f')}/{version}")
    return _download(meta["dist"]["tarball"], dest / f"published-{version}.tgz")


def changed_since_published(built: Path, built_version: str, published: Sequence[str],
                            spelling: "re.Pattern[str]", fetch, what: str) -> Tuple[bool, str]:
    """Whether `built` differs from the newest version of it on its registry."""
    import tempfile

    newest = newest_version(published, spelling)
    if newest is None:
        return True, f"{what}: nothing published yet"
    with tempfile.TemporaryDirectory() as tmp:
        theirs = package_files(fetch(newest, Path(tmp)), newest)
    diff = package_diff(package_files(built, built_version), theirs)
    if not diff:
        return False, f"{what}: identical to {newest}, which is already published"
    shown = ", ".join(diff[:5]) + (f" and {len(diff) - 5} more" if len(diff) > 5 else "")
    return True, f"{what}: {len(diff)} files differ from {newest}: {shown}"


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
    pairing = find_paired(github_releases(repo_name()))
    found = pairing.release
    set_output("digest", digest)
    if found:
        log(f"{found['tag_name']} was built from these sources ({pairing.why}); no browser build needed")
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


def cmd_set_build(args: argparse.Namespace) -> int:
    """upstream.sh names TAG's release number -- in the working tree only.

    The tag points at the tested main commit, whose upstream.sh names the floor
    the number was allocated from; the build takes the number from the tag.
    """
    m = _BROWSER_TAG.match(args.tag)
    if not m:
        die(f"{args.tag!r} is not a browser release tag")
    up = read_upstream_sh()
    if m["version"] != up["version"]:
        die(f"{args.tag} is Firefox {m['version']}, but upstream.sh builds {up['version']}")
    path = REPO_ROOT / "upstream.sh"
    path.write_text(re.sub(r"^release=.*$", f"release={m['prefix']}.{m['n']}", path.read_text(), flags=re.M))
    log(f"upstream.sh: release={m['prefix']}.{m['n']}")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    print(json.dumps(manifest(args.tag, args.digest, args.commit), indent=2))
    return 0


def _releases(args: argparse.Namespace) -> List[dict]:
    if getattr(args, "releases", None):
        return json.loads(Path(args.releases).read_text(encoding="utf-8"))
    return github_releases(repo_name())


def cmd_paired(args: argparse.Namespace) -> int:
    pairing = find_paired(_releases(args), Path(args.root).resolve())
    for rel in pairing.ahead:
        print(f"  {rel}")
    found = pairing.release
    if not found:
        die(f"no browser release was built from these sources: {pairing.why}. "
            "If this commit changed the browser, its build has failed or not finished; "
            "see that commit's run of the Release workflow.")
    log(f"paired with {found['tag_name']}: {pairing.why}")
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
    publish = True
    if args.channel == "prerelease":
        publish, why = library_changed(Path(args.root).resolve())
        log(why)
    set_output("publish", "true" if publish else "false")
    return 0


def library_changed(root: Path = REPO_ROOT) -> Tuple[bool, str]:
    """Whether HEAD ships anything the last library release did not.

    A docs- or CI-only merge publishes no library prerelease: it would be the
    same package under a new number.
    """
    tags = run(["git", "tag", "-l", "v*"], cwd=root, check=True).stdout.split()
    last = last_library_tag(tags)
    if last is None:
        return True, "no library release is tagged yet"
    diff = run(["git", "diff", "--name-only", last, "HEAD"], cwd=root, check=True).stdout.split()
    changed = sorted(f for f in diff if is_library_source(f))
    if not changed:
        return False, f"nothing a library release ships has changed since {last}"
    return True, f"{len(changed)} shipped files changed since {last}, e.g. {', '.join(changed[:3])}"


def cmd_lib_diff(args: argparse.Namespace) -> int:
    """Which registries get this release: those whose package it actually changes.

    lib-plan only knows that something a library ships moved since the last
    release. Here the packages are built, so each is compared, file by file, with
    the newest version on its own registry. The Python package and the npm
    package ship different things (a TypeScript-only change leaves the wheel
    byte-identical), so each registry is decided on its own; the version counter
    stays shared, which is why a registry can skip a number. A stable tag always
    publishes both: it is the maintainer's explicit release.
    """
    if args.channel == "stable":
        set_output("publish_pypi", "true")
        set_output("publish_npm", "true")
        return 0
    pypi, npm = registry_versions()
    py, py_why = changed_since_published(Path(args.wheel), args.py_version, pypi, _PY_VERSION,
                                         published_wheel, "PyPI")
    js, js_why = changed_since_published(Path(args.tarball), args.npm_version, npm, _NPM_VERSION,
                                         published_tarball, "npm")
    log(py_why)
    log(js_why)
    set_output("publish_pypi", "true" if py else "false")
    set_output("publish_npm", "true" if js else "false")
    return 0


def is_gate_check(name: str) -> bool:
    """The test pipeline's gate, run directly or called by release.yml."""
    return name == GATE_CHECK or name.endswith(f" / {GATE_CHECK}")


def _require_tested(sha: str) -> None:
    """The test pipeline's gate check passed on exactly this commit."""
    checks: List[dict] = []
    for page in range(1, 11):
        batch = http_json(
            f"https://api.github.com/repos/{repo_name()}/commits/{sha}/check-runs"
            f"?filter=latest&per_page=100&page={page}",
            headers=_gh_headers(),
        ).get("check_runs", [])
        checks += batch
        if len(batch) < 100:
            break
    if not any(is_gate_check(c.get("name", "")) and c.get("conclusion") == "success" for c in checks):
        die(f"'{GATE_CHECK}' has not passed on {sha[:10]}; nothing untested is released")


def _head() -> str:
    return run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True).stdout.strip()


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
    pairing = find_paired(github_releases(repo_name()))
    found = pairing.release
    if not found:
        die(f"no browser release was built from these sources: {pairing.why}")
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
    p = sub.add_parser("set-build"); p.add_argument("--tag", required=True); p.set_defaults(fn=cmd_set_build)
    p = sub.add_parser("manifest"); p.add_argument("--tag", required=True); p.add_argument("--digest", required=True)
    p.add_argument("--commit", required=True); p.set_defaults(fn=cmd_manifest)
    p = sub.add_parser("paired")
    p.add_argument("--root", default=str(REPO_ROOT), help="the checkout to pair (default: this one)")
    p.add_argument("--releases", metavar="JSON",
                   help="the releases as the GitHub API lists them, instead of asking it")
    p.set_defaults(fn=cmd_paired)
    p = sub.add_parser("lib-plan"); p.add_argument("--channel", choices=["prerelease", "stable"], required=True)
    p.add_argument("--tag")
    p.add_argument("--root", default=str(REPO_ROOT), help="the checkout to compare (default: this one)")
    p.set_defaults(fn=cmd_lib_plan)
    p = sub.add_parser("check-promotable"); p.add_argument("--tag", required=True)
    p.set_defaults(fn=cmd_check_promotable)
    p = sub.add_parser("stamp"); p.add_argument("--browser-tag", required=True)
    p.add_argument("--py-version", required=True); p.add_argument("--npm-version", required=True)
    p.set_defaults(fn=cmd_stamp)
    sub.add_parser("promote").set_defaults(fn=cmd_promote)
    p = sub.add_parser("lib-diff"); p.add_argument("--channel", choices=["prerelease", "stable"], required=True)
    p.add_argument("--wheel", required=True); p.add_argument("--tarball", required=True)
    p.add_argument("--py-version", required=True); p.add_argument("--npm-version", required=True)
    p.set_defaults(fn=cmd_lib_diff)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
