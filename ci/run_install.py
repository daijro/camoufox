#!/usr/bin/env python3
"""install gate: both packages, installed the way a user installs them.

Packs pythonlib and the npm package exactly as they would be published, installs
each into a clean environment with an empty cache, and runs the real
`camoufox fetch`: the browser, the GeoIP database and the fpgen model,
downloaded and put in place.

Then each installed package launches a browser the way a user's code does
(`from camoufox.sync_api import Camoufox`, `import { Camoufox } from
"camoufox"`): first the one `fetch` installed, then the browser under test
(`--browser`, the build the other suites run), so the installed path is
checked against the browser being merged and not only against the last
release. A local page records the request's User-Agent and runs the shared
probe (typescript/tests/fixtures/e2e/probe.js), then the probe clicks a button
and types into a text input through Playwright's locators while the page logs
the events. The launch must hold together: a stock Firefox User-Agent whose
major is the launched browser's application.ini version, the same in navigator
and on the wire, the fonts every Linux identity claims rendering from the
bundle, and a trusted click and trusted keystrokes that leave the typed text in
the input.

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
    python3 -m ci.run_install --tmpdir /mnt/install-tmp --browser <camoufox-bin>
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from . import release, results
from ._util import RESULTS_DIR, REPO_ROOT, STOCK_UA, WORK_DIR, run

PYTHONLIB = REPO_ROOT / "python"
TYPESCRIPT = REPO_ROOT / "typescript"
PROBE = TYPESCRIPT / "tests" / "fixtures" / "e2e" / "probe.js"
PYTHON_PROBE = TYPESCRIPT / "scripts" / "e2e" / "python_probe.py"
NODE_PROBE = TYPESCRIPT / "scripts" / "e2e" / "node_probe.mjs"
# Every Linux identity reports these (pythonlib's base set), so each must
# render from the bundle rather than fall back.
ESSENTIAL_FONTS = PYTHONLIB / "src" / "camoufox" / "essential-fonts.json"
LAUNCH = {"os": "linux", "headless": True}
# Lowercase, so each character is one keydown: a capital adds Shift's.
TYPED = "camoufox"
# The page writes each event into #events for the probe to read back: the DOM
# is shared with the isolated world page.evaluate runs in, page globals are not.
PAGE = b"""<!doctype html><title>install</title>
<button id="button">button</button><input id="input"><pre id="events"></pre>
<script>
for (const type of ["click", "keydown", "keyup"]) {
  document.addEventListener(type, (e) => {
    const event = {type, trusted: e.isTrusted, target: e.target.id};
    document.getElementById("events").textContent += JSON.stringify(event) + "\\n";
  });
}
</script>"""


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


def user_env(home: Path, tmpdir: Path) -> Dict[str, str]:
    """A user with an empty home: `fetch` installs there, and launches find it there."""
    return {"HOME": str(home), "XDG_CACHE_HOME": str(home / "cache"), "TMPDIR": str(tmpdir)}


def fetched_browser(cache: Path) -> Path:
    found = list(cache.glob("camoufox/browsers/*/*/camoufox-bin"))
    if len(found) != 1:
        raise SystemExit(f"expected one fetched browser under {cache}, found {found}")
    return found[0]


def browser_version(binary: Path) -> str:
    ini = configparser.ConfigParser()
    if not ini.read(binary.parent / "application.ini", encoding="utf-8"):
        raise SystemExit(f"no application.ini beside {binary}")
    return ini["App"]["Version"]


def identity_problems(probe: dict, header: str, version: str, essential: List[str]) -> List[str]:
    """Why the page's identity does not hold together; empty when it does."""
    problems = []
    claimed = probe["navigator"]["userAgent"]
    match = STOCK_UA.match(claimed)
    major = version.split(".", 1)[0]
    if not match:
        problems.append(f"navigator.userAgent is not stock Firefox's shape: {claimed}")
    elif match.groups() != (major, major):
        problems.append(f"the User-Agent claims rv:{match[1]} Firefox/{match[2]}, "
                        f"but the browser is Firefox {version}")
    if claimed != header:
        problems.append(f"navigator.userAgent {claimed!r} is not the request's User-Agent {header!r}")
    probed = [f for f in essential if f in probe["fonts"]]
    missing = [f for f in probed if not probe["fonts"][f]]
    if not probed:
        problems.append("the probe measures none of the fonts every Linux identity claims")
    elif missing:
        problems.append(f"fonts every Linux identity claims did not render: {missing}")
    return problems


def interaction_problems(events: List[dict], value: str, typed: str) -> List[str]:
    """Why the click and the typing did not reach the page as a user's would; empty when they did."""
    problems = []
    clicks = [e for e in events if e["type"] == "click"]
    if clicks != [{"type": "click", "trusted": True, "target": "button"}]:
        problems.append(f"expected one trusted click on the button, the page saw {clicks}")
    if value != typed:
        problems.append(f"typed {typed!r} into the input, which holds {value!r}")
    keys = [e for e in events if e["type"] != "click"]
    if sum(e["type"] == "keydown" for e in keys) != len(typed):
        problems.append(f"typed {len(typed)} keys, the page saw {keys}")
    stray = [e for e in keys if not e["trusted"] or e["target"] != "input"]
    if stray:
        problems.append(f"key events that were untrusted or missed the input: {stray}")
    return problems


@contextlib.contextmanager
def probe_page() -> Iterator[tuple]:
    """The local page, and the User-Agent header of each request for it."""
    headers: List[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- the stdlib's name
            # Only the page: the browser may also ask for /favicon.ico.
            if self.path == "/":
                headers.append(self.headers["User-Agent"])
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/", headers
    finally:
        server.shutdown()


def launch(result: results.GateResult, name: str, cmd: List[str], cwd: Path, env: Dict[str, str],
           binary: Path, label: str, extra: Dict[str, str], timeout: int) -> bool:
    """Launch `binary` through the installed package and check what the page saw."""
    test = f"{name}::launch {label}"
    essential = json.loads(ESSENTIAL_FONTS.read_text(encoding="utf-8"))["lin"]
    with probe_page() as (url, headers):
        request = {"mode": "interact", "url": url, "probe": str(PROBE), "text": TYPED,
                   "kwargs": {**LAUNCH, **extra}}
        proc = run(cmd, cwd=cwd, env=env, timeout=timeout, input=json.dumps(request))
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not proc.ok or not lines or len(headers) != 1:
        result.record(test, results.FAIL)
        result.note(f"{name}: launching {label} exited {proc.code}: " + proc.combined().strip()[-600:])
        return False
    out = json.loads(lines[-1])
    problems = (identity_problems(out["probe"], headers[0], browser_version(binary), essential)
                + interaction_problems(out["events"], out["value"], TYPED))
    for problem in problems:
        result.note(f"{name}, {label}: {problem}")
    result.record(test, results.FAIL if problems else results.PASS)
    return not problems


def fetch(result: results.GateResult, name: str, cmd: List[str], cwd: Path, home: Path, tmpdir: Path,
          tag: str, timeout: int) -> bool:
    cache = home / "cache"
    cache.mkdir(parents=True)
    env = user_env(home, tmpdir)
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


def launches(result: results.GateResult, name: str, cmd: List[str], cwd: Path, env: Dict[str, str],
             browser: Path, timeout: int) -> bool:
    """The fetched browser, then the browser under test, through one installed package."""
    fetched = fetched_browser(Path(env["XDG_CACHE_HOME"]))
    ok = launch(result, name, cmd, cwd, env, fetched, "the fetched browser", {}, timeout)
    return launch(result, name, cmd, cwd, env, browser, "the browser under test",
                  {"executable_path": str(browser)}, timeout) and ok


def python_package(result: results.GateResult, work: Path, tmpdir: Path, tag: str, browser: Path,
                   timeout: int) -> bool:
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
    home = work / "home"
    if not fetch(result, "pythonlib", [str(python), "-m", "camoufox", "fetch"], work, home, tmpdir, tag, timeout):
        return False
    # -I: the script's directory and PYTHONPATH stay off sys.path, so `camoufox`
    # is the installed package.
    return launches(result, "pythonlib", [str(python), "-I", str(PYTHON_PROBE)], work,
                    user_env(home, tmpdir), browser, timeout)


def npm_package(result: results.GateResult, work: Path, tmpdir: Path, tag: str, browser: Path,
                timeout: int) -> bool:
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
    home = work / "home"
    if not fetch(result, "typescript", ["npx", "--no-install", "camoufox", "fetch"], project, home, tmpdir,
                 tag, timeout):
        return False
    # A bare import resolves from the importing file, so the probe runs from
    # inside the project that installed the tarball.
    shutil.copy(NODE_PROBE, project / NODE_PROBE.name)
    return launches(result, "typescript", ["node", NODE_PROBE.name], project, user_env(home, tmpdir),
                    browser, timeout)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tmpdir", type=Path, required=True,
                        help="the temporary directory, on a different filesystem from the work directory")
    parser.add_argument("--browser-tag", help="the browser release to pin; default: the newest published")
    parser.add_argument("--browser", type=Path, required=True,
                        help="camoufox-bin of the browser under test, launched through each installed package")
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
        browser = args.browser.resolve()
        ok = python_package(result, args.work / "pythonlib", tmpdir, tag, browser, args.timeout)
        ok = npm_package(result, args.work / "typescript", tmpdir, tag, browser, args.timeout) and ok
    finally:
        release.PIN_FILE.write_text(unstamped, encoding="utf-8")
    result.finish(results.PASS if ok else results.FAIL).save(args.results_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
