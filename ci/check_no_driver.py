#!/usr/bin/env python3
"""Fail when driver (launcher) code comes back into this repository.

The camoufox driver -- the Python and TypeScript launcher, its fingerprint
data, CLI and MCP server -- lives in https://github.com/CamouBrowser/camoucore
and ships in the one `camoucore` package, as camoucore.camoufox (npm:
camoucore/camoufox). This repository is the browser plus the `camoufox` release
wrapper, which is that launcher under its own name and nothing else: one stub
per public camoucore.camoufox module, an exact camoucore pin and
camoufox_pin/browser-pin.json (camoucore's RELEASING.md, "The wrapper
packages"). Launcher code added here would drift from the real launcher, so a
pull request that adds any -- a new module, or a stub that does more than
alias -- fails here, pointing at camoucore.

    python3 -m ci.check_no_driver            # the tracked files of this checkout
"""

from __future__ import annotations

import re
import sys
from pathlib import PurePosixPath
from typing import Callable, Iterable, List, Optional

from ._util import REPO_ROOT, run

CAMOUCORE = "https://github.com/CamouBrowser/camoucore"

# Where the old in-tree drivers lived, and the driver's package name: nothing
# may be tracked under them.
DRIVER_DIRS = ("python", "typescript", "pythonlib", "src")
# Source suffixes a launcher module would have.
CODE_SUFFIXES = (".py", ".pyi", ".ts", ".mts", ".cts", ".js", ".mjs", ".cjs")
# Code is fine here: the browser, its tests and tools, and the CI pipeline.
CODE_ROOTS = ("browser", "ci", ".github")
# The whole of the release wrapper, file by file: anything else under these
# directories is driver code in the wrong place.
WRAPPER = {
    "camoufox": {"camoufox/__init__.py", "camoufox/__main__.py", "camoufox/LICENSE"},
    "camoufox_pin": {"camoufox_pin/__init__.py", "camoufox_pin/browser-pin.json"},
    "npm": {"npm/index.js", "npm/index.d.ts", "npm/cli.js", "npm/package.json", "npm/README.md",
            "npm/LICENSE", "npm/camoufox_pin/browser-pin.json"},
}
# Besides those, camoufox/ holds one stub per public camoucore.camoufox module,
# exactly this (RELEASING.md); ci/check_wrapper.py checks the set against an
# installed camoucore.
STUB = """import importlib
import sys

sys.modules[__name__] = importlib.import_module("camoucore.camoufox.{module}")
"""


def is_stub(rel: str, text: Optional[str]) -> bool:
    """Whether `rel` is a camoufox/<module>.py alias stub holding exactly STUB."""
    path = PurePosixPath(rel)
    return (len(path.parts) == 2 and path.parts[0] == "camoufox" and path.suffix == ".py"
            and text == STUB.format(module=path.stem))


def violation(rel: str, read: Callable[[str], Optional[str]] = lambda rel: None) -> Optional[str]:
    """Why tracked path `rel` is driver code, or None. `read` gives a file's text."""
    parts = PurePosixPath(rel).parts
    top = parts[0]
    if len(parts) > 1 and top in DRIVER_DIRS:
        return f"{top}/ is where the driver used to live"
    if top in WRAPPER:
        if len(parts) > 1 and rel not in WRAPPER[top]:
            if top == "camoufox" and is_stub(rel, read(rel)):
                return None
            extra = ", and camoufox/<module>.py alias stubs" if top == "camoufox" else ""
            return f"the release wrapper's {top}/ holds only {', '.join(sorted(WRAPPER[top]))}{extra}"
        return None
    if rel.endswith(CODE_SUFFIXES) and top not in CODE_ROOTS:
        return "launcher code belongs in the driver"
    return None


def _read(rel: str) -> Optional[str]:
    try:
        return (REPO_ROOT / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def violations(paths: Iterable[str], read: Callable[[str], Optional[str]] = _read) -> List[str]:
    return [f"{p}: {why}" for p in paths if (why := violation(p, read))]


# `from camoufox.<module> import ...` / `import camoufox.<module>` in Python code.
IMPORT = re.compile(r"^[ \t]*(?:from|import)[ \t]+camoufox\.([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def unaliased_imports(paths: Iterable[str], read: Callable[[str], Optional[str]] = _read) -> List[str]:
    """Imports of a camoufox.<module> the wrapper has no stub for.

    The wrapper aliases only camoucore.camoufox's public modules; a browser test
    that imports a camoucore core module (virtdisplay, fpgen_model, ...) under
    the camoufox name fails at run time, often only on the runner that reaches
    it, so it fails here instead. Import it from camoucore.
    """
    paths = list(paths)
    aliased = {PurePosixPath(p).stem for p in paths
               if PurePosixPath(p).parent == PurePosixPath("camoufox") and p.endswith(".py")}
    found = []
    for rel in paths:
        if not rel.endswith(".py") or PurePosixPath(rel).parts[0] not in CODE_ROOTS:
            continue
        text = read(rel) or ""
        for match in IMPORT.finditer(text):
            if match[1] not in aliased:
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{rel}:{line}: camoufox.{match[1]} is not a camoucore.camoufox module "
                             f"the wrapper aliases; import it from camoucore")
    return found


def main(argv: Optional[List[str]] = None) -> int:
    del argv
    paths = run(["git", "ls-files"], cwd=REPO_ROOT, check=True).stdout.splitlines()
    found = violations(paths)
    unaliased = unaliased_imports(paths)
    for line in unaliased:
        print(f"::error file={line.split(':', 1)[0]}::{line}")
    if not found:
        if not unaliased:
            print("no driver code in this repository")
        return 1 if unaliased else 0
    for line in found:
        print(f"::error file={line.split(':', 1)[0]}::{line}. Driver and launcher changes "
              f"go to {CAMOUCORE} (see CONTRIBUTING.md).")
    print(f"\n{len(found)} driver file(s) here. The camoufox driver lives in {CAMOUCORE}; "
          "this repository is the browser and the release wrapper. Open the change there, "
          "and pin the released camoucore in pyproject.toml and npm/package.json "
          "(or set ci/driver-ref to test an unreleased camoucore ref).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
