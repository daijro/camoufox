r"""
Camoufox must expose web content the same files a stock Firefox release does.

Twelve chrome/resource packages are flagged `contentaccessible=yes`. Any page,
from any origin, can load their files as subresources -- ALLOW_CHROME in
caps/nsScriptSecurityManager.cpp checks the target package's flag and never the
source -- so a file Camoufox adds, drops or changes there is a build tell:

    const s = document.createElement('script');
    s.onload = () => BUILD_IS_NOT_STOCK;
    s.src = 'chrome://browser/content/browser-development-helpers.js';

Every other registered chrome package and resource host is visible too: content
processes receive all of them, and the Worker constructor returns for a
registered name and throws for an absent one. hCaptcha's hsw.js runs exactly
this against chrome://juggler (daijro/camoufox#847):

    try { new Worker('chrome://juggler/content/content/WorkerMain.js'); BUILD_IS_NOT_STOCK; }
    catch (e) { /* SecurityError, as in stock Firefox */ }

Three checks, against scripts/data/contentaccessible-manifest.json (recorded from
a stock release by scripts/gen-contentaccessible-manifest.py): the files of
every contentaccessible package and their SHA-256, and the names every manifest
registers. Then a page actually loads a sample and constructs the Workers, so
the static diff cannot pass while the surface is really different.

    python browser/tests/playwright/patches/contentaccessible-parity.py
"""

import importlib.util
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

BROWSER_ROOT = Path(__file__).resolve().parents[3]

# The jar listing is the generator's, so the guard reads a build exactly the way
# the manifest was recorded.
_spec = importlib.util.spec_from_file_location(
    "gen_contentaccessible_manifest", BROWSER_ROOT / "scripts" / "gen-contentaccessible-manifest.py"
)
_generator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_generator)
jar_hashes = _generator.jar_hashes
tree_hashes = _generator.tree_hashes
registrations = _generator.registrations
MANIFEST = _generator.OUT

# A page reads a file's bytes only through what the file does when loaded: an
# image's pixels, a stylesheet's rules, a script's side effects. Markup loads as
# none of those, so only its presence has to match stock.
PRESENCE_ONLY = (".html", ".xhtml")

# Differences no page can reach, with the reason. The guard fails when one
# matches stock again, so the list cannot outlive the difference.
UNREACHABLE_DIFFERENCES = {
    "chrome/browser/content/browser/parent/ext-browser.js":
        "disable-extension-newtab.patch; loaded from a page it throws on ChromeUtils "
        "at line 11, before the patched arrow function",
    "chrome/browser/content/browser/parent/ext-tabs.js":
        "disable-extension-newtab.patch; loaded from a page it throws on ChromeUtils "
        "at line 7, before the patched class",
}

# Loaded from a page and asserted against stock Firefox 152.0.4. Each entry is
# (url, must_load). Regenerate by running the same probe against a stock build.
LIVE_PROBES = [
    ("chrome://global/content/aboutSupport.js", True),
    ("chrome://global/content/crashes.js", True),
    ("chrome://browser/content/browser-init.js", True),
    ("chrome://browser/content/browser-development-helpers.js", False),
    ("chrome://browser/content/does-not-exist-control.js", False),
]

# Constructed as Workers from a page and asserted against stock Firefox 156.0.1.
# Each entry is (url, constructor_returns): it returns for a registered package
# and throws a SecurityError for an absent one.
WORKER_PROBES = [
    ("chrome://juggler/content/content/WorkerMain.js", False),
    ("chrome://global/content/aboutSupport.js", True),
]

WORKER_PROBE_JS = """
([urls]) => {
  const out = {};
  for (const u of urls) {
    try { new Worker(u).terminate(); out[u] = true; } catch (e) { out[u] = false; }
  }
  return out;
}
"""

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


def package_hashes(root: Path, jar: str, prefixes: list) -> dict:
    """Member -> SHA-256 for one package, from the jar if packaged, else from the
    tree. `mach build` leaves dist/bin without omni.ja: the same resources sit
    as loose files at their jar paths, under dist/bin/browser/ for
    browser/omni.ja and dist/bin/ for omni.ja. CI tests that unpackaged tree.

    Returns None when neither is present, so the caller can say which.
    """
    path = root / jar
    if path.exists():
        return jar_hashes(path, prefixes)
    base = root / 'browser' if jar == 'browser/omni.ja' else root
    if (base / 'chrome').is_dir():
        return tree_hashes(base, prefixes)
    return None


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

    for key, spec in sorted(manifest["packages"].items()):
        jar = key.split("|", 1)[0]
        built = package_hashes(root, jar, spec["prefixes"])
        if built is None:
            failures.append(
                f"{jar} not found next to the binary, and no loose chrome/ tree "
                f"to read instead -- nothing to compare against stock"
            )
            return
        stock = spec["files"]
        problems = [f"MISSING vs stock -- {n}" for n in sorted(stock.keys() - built.keys())]
        problems += [f"EXTRA vs stock -- {n}" for n in sorted(built.keys() - stock.keys())]
        for name in sorted(stock.keys() & built.keys()):
            differs = built[name] != stock[name] and not name.endswith(PRESENCE_ONLY)
            if differs and name not in UNREACHABLE_DIFFERENCES:
                problems.append(f"CHANGED vs stock -- {name}")
            elif not differs and name in UNREACHABLE_DIFFERENCES:
                problems.append(f"matches stock again, drop it from UNREACHABLE_DIFFERENCES -- {name}")
        failures += [f"{key}: {p}" for p in problems]
        if not problems:
            print(f"  ok  {key.split('|', 2)[2]:32} {len(built):>5} files")

    built = registrations(root)
    for kind, stock_names in sorted(manifest["registered"].items()):
        extra = sorted(set(built[kind]) - set(stock_names))
        missing = sorted(set(stock_names) - set(built[kind]))
        failures += [f"registered {kind}: EXTRA vs stock -- {n} (pages can detect it)" for n in extra]
        failures += [f"registered {kind}: MISSING vs stock -- {n}" for n in missing]
        if not extra and not missing:
            print(f"  ok  registered {kind:23} {len(built[kind]):>5} names")


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
        return {
            "loads": page.evaluate(PROBE_JS, [urls]),
            "workers": page.evaluate(WORKER_PROBE_JS, [[u for u, _ in WORKER_PROBES]]),
        }


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

    for url, returns in WORKER_PROBES:
        got = results["workers"].get(url)
        if got != returns:
            verb = "throws but stock returns a Worker" if returns else "returns a Worker but stock throws"
            failures.append(f"live: new Worker({url!r}) {verb}")
        else:
            print(f"  ok  {'returns' if returns else 'throws':7} new Worker({url})")

    for url, must_load in LIVE_PROBES:
        got = results["loads"].get(url)
        if got is None:
            failures.append(f"live: {url} timed out")
        elif got != must_load:
            verb = "did not load but stock loads it" if must_load else "loaded but stock does not ship it"
            failures.append(f"live: {url} {verb}")
        else:
            print(f"  ok  {'loads' if must_load else 'absent':7} {url}")


def main() -> int:
    if not MANIFEST.exists():
        print(f"FAIL: {MANIFEST.relative_to(BROWSER_ROOT)} is missing; generate it first")
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
