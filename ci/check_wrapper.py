#!/usr/bin/env python3
"""Check an installed `camoufox` release wrapper against camoucore's contract.

camoucore's RELEASING.md, "The wrapper packages", says what the `camoufox`
package (PyPI and npm) must be: camoucore.camoufox (npm: camoucore/camoufox)
under its own name, with no launcher code of its own, and the browser pin that
wins over camoucore's. This checks an install of it, with the Python that has
the wrapper installed (not this checkout's sources: run it outside the
repository root, or the root camoufox/ shadows the installed one):

    <venv>/bin/python ci/check_wrapper.py [--pin-tag TAG] [--exact-camoucore] [--npm-dir DIR]

  * every public submodule of camoucore.camoufox is the same module object as
    camoufox.<module> (a new camoucore module without a stub here fails), and
    `camoufox` exports what camoucore.camoufox does;
  * the pin the launcher reads is the wrapper's camoufox_pin/browser-pin.json
    (with --pin-tag, naming TAG);
  * `camoufox --help` and `python -m camoufox --help` run camoucore's CLI;
  * --exact-camoucore: the installed camoucore is the release the wrapper pins
    (a ci/driver-ref install is a camoucore ref, whatever its version);
  * --npm-dir DIR: in a project with the npm wrapper and camoucore installed,
    `camoufox` exports exactly camoucore/camoufox, the wrapper's pin wins,
    `camoufox --help` runs and `camoufox mcp` reaches the MCP server.

Standalone (no imports from ci/), so any interpreter can run it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

LAUNCHER = "camoufox"
IMPL = f"camoucore.{LAUNCHER}"
PIN_PACKAGE = f"{LAUNCHER}_pin"


def public_modules(impl) -> List[str]:
    """Every camoucore.camoufox module a user can import: no leading underscore, plus __version__."""
    names = {m.name for m in pkgutil.iter_modules(impl.__path__) if not m.name.startswith("_")}
    return sorted(names | {"__version__"})


def check_python(pin_tag: Optional[str], exact: bool, scratch: Path) -> List[str]:
    from importlib import metadata

    problems: List[str] = []
    wrapper = importlib.import_module(LAUNCHER)
    impl = importlib.import_module(IMPL)
    wrapper_dir = Path(wrapper.__file__).parent

    for name in public_modules(impl):
        try:
            alias = importlib.import_module(f"{LAUNCHER}.{name}")
        except ImportError as err:
            problems.append(f"{LAUNCHER}.{name} does not import ({err}): the wrapper needs a stub for it")
            continue
        if alias is not importlib.import_module(f"{IMPL}.{name}"):
            problems.append(f"{LAUNCHER}.{name} is not {IMPL}.{name}")
    # A stub for a module camoucore no longer has.
    for stub in sorted(wrapper_dir.glob("*.py")):
        if stub.stem in ("__init__", "__main__"):
            continue
        if stub.stem not in public_modules(impl):
            problems.append(f"{stub.name}: {IMPL} has no public module {stub.stem}")
    if wrapper.__all__ != impl.__all__:
        problems.append(f"{LAUNCHER}.__all__ differs from {IMPL}.__all__")
    problems += [f"{LAUNCHER}.{n} is not {IMPL}.{n}" for n in impl.__all__
                 if getattr(wrapper, n, None) is not getattr(impl, n)]
    # One copy of each module: nothing loaded a second time under the wrapper's name.
    twice = [m for m in sys.modules if m.startswith(f"{LAUNCHER}.") and sys.modules[m].__name__ == m]
    if twice:
        problems.append(f"loaded twice, as wrapper modules: {', '.join(sorted(twice))}")

    browser_pin = importlib.import_module(f"{IMPL}.browser_pin")
    from importlib.resources import files

    ours = Path(str(files(PIN_PACKAGE) / "browser-pin.json"))
    if Path(browser_pin.pin_file()).resolve() != ours.resolve():
        problems.append(f"the launcher reads {browser_pin.pin_file()}, not the wrapper's {ours}")
    if pin_tag is not None:
        pin = browser_pin.load_pin()
        if pin is None or pin.tag != pin_tag:
            problems.append(f"the launcher's pin is {pin and pin.tag}, expected {pin_tag}")

    requires = metadata.requires(LAUNCHER) or []
    pinned = [r for r in requires if re.match(r"camoucore\s*\(?==", r)]
    if len(pinned) != 1:
        problems.append(f"{LAUNCHER}'s metadata does not pin exactly one camoucore: {requires}")
    elif exact:
        want = re.search(r"==\s*([^\s);]+)", pinned[0])[1]
        if metadata.version("camoucore") != want:
            problems.append(f"camoucore {metadata.version('camoucore')} is installed; the wrapper pins {want}")

    # Out of the repository, so its camoufox/ does not shadow the installed one.
    bindir = Path(sys.executable).parent
    script = shutil.which(LAUNCHER, path=str(bindir)) or shutil.which(LAUNCHER)
    commands = {f"python -m {LAUNCHER}": [sys.executable, "-m", LAUNCHER, "--help"]}
    if script:
        commands[LAUNCHER] = [script, "--help"]
    else:
        problems.append(f"no `{LAUNCHER}` console script beside {sys.executable}")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for what, cmd in commands.items():
        out = subprocess.run(cmd, cwd=scratch, env=env, capture_output=True, text=True)
        if out.returncode != 0 or "fetch" not in out.stdout:
            problems.append(f"`{what} --help` failed ({out.returncode}): {out.stderr.strip()[-400:]}")
    print(f"python: {LAUNCHER} {metadata.version(LAUNCHER)} -> camoucore {metadata.version('camoucore')}, "
          f"{len(public_modules(impl))} modules aliased, pin {ours}")
    return problems


NODE_PROBE = r"""
import { createRequire } from "node:module";
const require = createRequire(process.cwd() + "/");
const [pinTag] = process.argv.slice(1);
const problems = [];
const impl = await import("camoucore/camoufox");
const wrapper = await import("camoufox");
const a = Object.keys(impl).sort(), b = Object.keys(wrapper).sort();
if (JSON.stringify(a) !== JSON.stringify(b)) problems.push("camoufox exports differ from camoucore/camoufox");
for (const k of a) if (wrapper[k] !== impl[k]) problems.push(`camoufox.${k} is not camoucore/camoufox's`);
const pin = require("camoufox/camoufox_pin/browser-pin.json");
const { loadPin } = await import("camoucore/camoufox/browser-pin.js");
const read = loadPin();
if ((read?.tag ?? null) !== (pin.tag ?? null)) problems.push(`the launcher reads pin ${read?.tag}, the wrapper ships ${pin.tag}`);
if (pinTag && pin.tag !== pinTag) problems.push(`the wrapper pins ${pin.tag}, expected ${pinTag}`);
const ours = require("camoufox/package.json"), core = require("camoucore/package.json");
if (ours.dependencies?.camoucore !== core.version) problems.push(`camoucore ${core.version} is installed; the wrapper pins ${ours.dependencies?.camoucore}`);
if (ours.peerDependencies?.["playwright-core"] !== core.peerDependencies?.["playwright-core"])
  problems.push(`playwright-core peer ${ours.peerDependencies?.["playwright-core"]} != camoucore's ${core.peerDependencies?.["playwright-core"]}`);
console.log(JSON.stringify({ problems, wrapper: ours.version, camoucore: core.version, exports: a.length, pin: pin.tag ?? null }));
"""


def check_npm(npm_dir: Path, pin_tag: Optional[str], exact: bool) -> List[str]:
    problems: List[str] = []
    out = subprocess.run(["node", "--input-type=module", "-e", NODE_PROBE, pin_tag or ""],
                         cwd=npm_dir, capture_output=True, text=True)
    if out.returncode != 0:
        return [f"npm: the probe failed: {out.stderr.strip()[-800:]}"]
    report = json.loads(out.stdout.strip().splitlines()[-1])
    for p in report["problems"]:
        # A ci/driver-ref install is a camoucore ref, whatever version it carries.
        if not exact and p.startswith("camoucore ") and "the wrapper pins" in p:
            continue
        problems.append(f"npm: {p}")
    bin_ = npm_dir / "node_modules" / ".bin" / LAUNCHER
    helped = subprocess.run([str(bin_), "--help"], cwd=npm_dir, capture_output=True, text=True)
    if helped.returncode != 0 or "fetch" not in helped.stdout:
        problems.append(f"npm: `{LAUNCHER} --help` failed ({helped.returncode}): {helped.stderr.strip()[-400:]}")
    # A stray positional: the MCP server refuses with its usage before loading
    # anything, so this needs no browser.
    mcp = subprocess.run([str(bin_), "mcp", "extra"], cwd=npm_dir, capture_output=True, text=True)
    if mcp.returncode != 2 or f"usage: {LAUNCHER} mcp" not in mcp.stderr:
        problems.append(f"npm: `{LAUNCHER} mcp` did not reach the MCP server ({mcp.returncode}): "
                        f"{mcp.stderr.strip()[-400:]}")
    print(f"npm: {LAUNCHER} {report['wrapper']} -> camoucore {report['camoucore']}, "
          f"{report['exports']} exports, pin {report['pin']}")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pin-tag", help="the browser tag the installed pin must name")
    ap.add_argument("--exact-camoucore", action="store_true",
                    help="the installed camoucore must be the version the wrapper pins")
    ap.add_argument("--npm-dir", type=Path, help="a project with the npm wrapper installed")
    ap.add_argument("--no-python", action="store_true", help="check only the npm install")
    args = ap.parse_args(argv)
    problems: List[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        if not args.no_python:
            problems += check_python(args.pin_tag, args.exact_camoucore, Path(scratch))
    if args.npm_dir:
        problems += check_npm(args.npm_dir.resolve(), args.pin_tag, args.exact_camoucore)
    for p in problems:
        print(f"::error::camoufox wrapper: {p}", file=sys.stderr)
    if not problems:
        print("the camoufox wrapper is camoucore's launcher")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
