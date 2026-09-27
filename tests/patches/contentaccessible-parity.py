r"""
Camoufox must expose web content the same files a stock Firefox release does.

Twelve chrome/resource packages are flagged `contentaccessible=yes`. Any page,
from any origin, can load their files as subresources -- ALLOW_CHROME in
caps/nsScriptSecurityManager.cpp checks the target package's flag and never the
source -- so a file Camoufox adds or drops there is a one-line build tell:

    const s = document.createElement('script');
    s.onload = () => BUILD_IS_NOT_STOCK;
    s.src = 'chrome://browser/content/browser-development-helpers.js';

Two checks. The file set of every package is diffed against
scripts/data/contentaccessible-manifest.json (recorded from a stock release by
scripts/gen-contentaccessible-manifest.py). Then a page actually loads a sample,
so the static diff cannot pass while the surface is really different.

    python tests/patches/contentaccessible-parity.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# The live probe drives a real browser, and a wedged launch would otherwise hang
# the whole patch-guard run. Fail loudly instead.
LIVE_TIMEOUT_S = 180

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = REPO_ROOT / "scripts" / "data" / "contentaccessible-manifest.json"

# Loaded from a page and asserted against stock Firefox 152.0.4. Each entry is
# (url, must_load). Regenerate by running the same probe against a stock build.
LIVE_PROBES = [
    ("chrome://global/content/aboutSupport.js", True),
    ("chrome://global/content/crashes.js", True),
    ("chrome://browser/content/browser-init.js", True),
    ("chrome://browser/content/browser-development-helpers.js", False),
    ("chrome://browser/content/does-not-exist-control.js", False),
]

PROBE_JS = """
async ([urls]) => {
  const out = {};
  for (const u of urls) {
    out[u] = await new Promise(res => {
      const s = document.createElement('script');
      s.onload = () => res(true);
      s.onerror = () => res(false);
      s.src = u;
      document.head.appendChild(s);
      setTimeout(() => res(null), 5000);
    });
  }
  return out;
}
"""


def loose_entries(base: Path) -> dict:
    """Member -> size, for an UNPACKAGED build.

    `mach build` leaves dist/bin without omni.ja: the same resources sit as
    loose files, at exactly the paths they would have inside the jar, under
    dist/bin/browser/ for browser/omni.ja and dist/bin/ for omni.ja. CI tests the
    unpackaged tree (see tests.yml, "Package the binary for the test jobs" --
    there is no omni.ja to rebuild there), so requiring the jar made this guard
    unrunnable on exactly the builds it is meant to gate.
    """
    out = {}
    for f in base.rglob('*'):
        if f.is_file():
            out[f.relative_to(base).as_posix()] = f.stat().st_size
    return out


def package_listing(root: Path, jar: str) -> dict:
    """The file set of one jar, from the jar if packaged, else from the tree.

    Returns None when neither is present, so the caller can say which.
    """
    path = root / jar
    if path.exists():
        return zip_entries(path)
    base = root / 'browser' if jar == 'browser/omni.ja' else root
    # chrome/ is the only part of dist/bin the manifest describes; walking all
    # of dist/bin would also pull in the binary, the fonts and the libs.
    if (base / 'chrome').is_dir():
        return loose_entries(base)
    return None


def zip_entries(jar: Path) -> dict:
    """Member -> size. unzip, not zipfile: Firefox's optimized jars put the
    central directory at the front and zipfile cannot open them."""
    out = subprocess.run(["unzip", "-l", str(jar)], capture_output=True, text=True).stdout
    entries = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and not parts[3].endswith("/"):
            entries[parts[3]] = int(parts[0])
    return entries


def static_check(binary: Path, manifest: dict, failures: list) -> None:
    root = binary.parent
    ini = root / "application.ini"
    if ini.exists():
        match = re.search(r"^Version=(.+)$", ini.read_text(errors="replace"), re.M)
        # Camoufox appends its own release to the Firefox version ("152.0.4-beta.30");
        # only the Firefox part decides whether the recorded file set still applies.
        built = match.group(1).strip().split("-")[0] if match else "unknown"
        if built != manifest["firefox_version"]:
            failures.append(
                f"manifest records Firefox {manifest['firefox_version']} but this build is "
                f"{built} -- re-run scripts/gen-contentaccessible-manifest.py against a "
                f"stock {built} release"
            )
            return

    listings = {}
    for jar in ("browser/omni.ja", "omni.ja"):
        listing = package_listing(root, jar)
        if listing is None:
            failures.append(
                f"{jar} not found next to the binary, and no loose chrome/ tree "
                f"to read instead -- nothing to compare against stock"
            )
            return
        listings[jar] = listing

    for key, spec in sorted(manifest["packages"].items()):
        jar = key.split("|", 1)[0]
        built = sorted(
            name for name in listings[jar]
            if any(name.startswith(p) for p in spec["prefixes"])
        )
        stock = set(spec["files"])
        missing = sorted(stock - set(built))
        extra = sorted(set(built) - stock)
        for name in missing:
            failures.append(f"{key}: MISSING vs stock -- {name}")
        for name in extra:
            failures.append(f"{key}: EXTRA vs stock -- {name}")
        if not missing and not extra:
            print(f"  ok  {key.split('|', 2)[2]:32} {len(built):>5} files")


PROBE_MARK = "PROBE-RESULT "


def run_probe(binary: Path) -> dict:
    """The probe itself, run in a child process (see live_check)."""
    from camoufox.sync_api import Camoufox

    urls = [u for u, _ in LIVE_PROBES]
    # i_know_what_im_doing is what makes executable_path stick; without it the
    # launcher falls back to the downloaded official build and this guard would
    # silently measure a different browser.
    with Camoufox(
        headless=True, executable_path=str(binary), env={}, i_know_what_im_doing=True
    ) as browser:
        page = browser.new_page()
        page.goto("about:blank")
        return page.evaluate(PROBE_JS, [urls])


def live_check(binary: Path, failures: list) -> None:
    """Drive a real browser, in a CHILD PROCESS under a timeout.

    Playwright's sync API blocks without servicing Python signals, so an
    in-process alarm cannot bound a wedged launch -- only killing the process
    can, and an unbounded guard would hang the whole patch-guard run.
    """
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe", str(binary)],
        capture_output=True, text=True, timeout=LIVE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        failures.append(f"live probe failed: {proc.stderr.strip().splitlines()[-1:] or proc.stdout}")
        return
    # The launcher may print to stdout first -- on a fresh machine the first
    # launch downloads the default addons and reports progress -- so read the
    # marked result line, not the whole stream.
    marked = [line for line in proc.stdout.splitlines() if line.startswith(PROBE_MARK)]
    if not marked:
        failures.append(f"live probe printed no result line: {proc.stdout.strip()[-300:]!r}")
        return
    results = json.loads(marked[-1][len(PROBE_MARK):])

    for url, must_load in LIVE_PROBES:
        got = results.get(url)
        if got is None:
            failures.append(f"live: {url} timed out")
        elif got != must_load:
            verb = "did not load but stock loads it" if must_load else "loaded but stock does not ship it"
            failures.append(f"live: {url} {verb}")
        else:
            print(f"  ok  {'loads' if must_load else 'absent':7} {url}")


def main() -> int:
    if not MANIFEST.exists():
        print(f"FAIL: {MANIFEST.relative_to(REPO_ROOT)} is missing; generate it first")
        return 1
    manifest = json.loads(MANIFEST.read_text())
    binary = resolve_binary()
    failures = []

    print(f"Stock baseline: Firefox {manifest['firefox_version']}, "
          f"{sum(len(p['files']) for p in manifest['packages'].values())} files "
          f"in {len(manifest['packages'])} packages\n")

    print("Package file sets:")
    static_check(binary, manifest, failures)
    print("\nLoaded from a page:")
    try:
        live_check(binary, failures)
    except subprocess.TimeoutExpired:
        failures.append(f"live probe did not finish within {LIVE_TIMEOUT_S}s (wedged launch?)")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"live probe could not run: {exc}")

    print()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: the content-reachable surface matches a stock Firefox release.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        print(PROBE_MARK + json.dumps(run_probe(Path(sys.argv[2]))))
        sys.exit(0)
    sys.exit(main())
