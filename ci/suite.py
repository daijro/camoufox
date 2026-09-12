#!/usr/bin/env python3
"""Materialise upstream's Playwright suite at the tag this run resolved to.

`tests/` in this repository is a maintained fork of a ~v1.55-era playwright-python
suite -- roughly 1800 semantic lines of Camoufox adaptations sit on top of it.
That fork is the right thing to run for regression detection, and the wrong
thing to run for conformance, because it cannot tell you about a test upstream
added last month.

So the harness runs both, and this module builds the second one: a clean,
unmodified checkout of upstream's suite at the exact tag Playwright shipped for
the Firefox being targeted, plus a virtualenv holding that same version of
playwright-python. Nothing here is committed; it is rebuilt per run, which is
what "pull the latest suite for that specific run" has to mean if the result is
going to be trustworthy.

Run:
    python3 -m ci.suite --tag v1.62.0
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import List, Optional

from ._util import CI_DIR, WORK_DIR, die, log, run, write_json

TARBALL = "https://github.com/microsoft/playwright-python/archive/refs/tags/{tag}.tar.gz"


def fetch(tag: str, dest: Path) -> Path:
    """Download and extract playwright-python at `tag`."""
    dest.mkdir(parents=True, exist_ok=True)
    checkout = dest / f"playwright-python-{tag}"
    if (checkout / "tests").is_dir():
        log(f"reusing existing checkout {checkout}")
        return checkout

    archive = dest / f"{tag}.tar.gz"
    url = TARBALL.format(tag=tag)
    log(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=180) as resp:  # noqa: S310
        archive.write_bytes(resp.read())

    staging = dest / f"_extract-{tag}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        # Refuse path traversal rather than trusting the archive.
        for member in tar.getmembers():
            target = (staging / member.name).resolve()
            if not str(target).startswith(str(staging.resolve())):
                die(f"refusing to extract {member.name}: escapes the staging directory")
        tar.extractall(staging)  # noqa: S202 -- members validated above

    roots = [p for p in staging.iterdir() if p.is_dir()]
    if len(roots) != 1:
        die(f"unexpected archive layout for {tag}: {[p.name for p in roots]}")
    shutil.rmtree(checkout, ignore_errors=True)
    roots[0].rename(checkout)
    shutil.rmtree(staging, ignore_errors=True)
    archive.unlink(missing_ok=True)
    log(f"upstream suite at {checkout}")
    return checkout


def make_venv(checkout: Path, tag: str, *, reuse: bool = True) -> Path:
    """A virtualenv holding the playwright-python release under test.

    The suite is version-locked to its own client library, so it gets its own
    environment rather than whatever the vendored suite happens to have.
    """
    venv = checkout / ".venv"
    python = venv / "bin" / "python"
    if reuse and python.exists():
        log(f"reusing venv {venv}")
        return python

    run([sys.executable, "-m", "venv", str(venv)], check=True)
    run([str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)

    # Install the suite's OWN pins, not a hand-picked list.
    #
    # Guessing them cost a full CI cycle: pytest-asyncio was pinned at 0.21.2
    # while v1.62.0 needs 1.4.0, and upstream's pyproject sets
    # asyncio_default_fixture_loop_scope = "session" -- an option 0.21 does not
    # understand. Its session-scoped browser fixtures then got a function-scoped
    # event loop and every single test errored at setup with ScopeMismatch,
    # which reads like the browser is broken and is not.
    #
    # The suite knows what it needs, and a future tag that changes its pins just
    # works instead of failing the same way again.
    requirements = checkout / "local-requirements.txt"
    if requirements.exists():
        run([str(python), "-m", "pip", "install", "--quiet", "-r", str(requirements)], check=True)
    else:
        log(f"{requirements} is missing; falling back to a minimal set", level="WARN")
        run([str(python), "-m", "pip", "install", "--quiet",
             "pytest", "pytest-asyncio", "pytest-timeout", "Pillow", "pixelmatch"], check=True)

    # The client the suite is written against, which its own requirements file
    # deliberately does not pin -- it is the package under test upstream.
    version = tag.lstrip("v")
    run([str(python), "-m", "pip", "install", "--quiet", f"playwright=={version}"], check=True)

    # ci/pw_camoufox_plugin.py reads ci/skiplist.yml from inside this
    # interpreter, so PyYAML has to be here and not just in the outer
    # environment. Without it every shard dies in pytest_configure.
    run([str(python), "-m", "pip", "install", "--quiet", "PyYAML>=6.0"], check=True)

    # Playwright refuses to start if its own browser registry is empty, even
    # when every launch is redirected at our binary.
    run([str(venv / "bin" / "playwright"), "install", "firefox"], timeout=1800)
    return python


def unshadow(checkout: Path) -> None:
    """Stop the checkout's own `playwright/` directory shadowing the wheel.

    pytest runs with the repository root on `sys.path`, so `import playwright`
    resolves to the *source* tree rather than the installed release. That copy
    has no generated `_repo_version.py` and no bundled Node driver, so every
    test dies at collection with

        ModuleNotFoundError: No module named 'playwright._repo_version'

    which reads like a broken install and is not. Moving it aside makes the
    suite import the real, installed client -- which is what we want to be
    testing against anyway.
    """
    source = checkout / "playwright"
    if not source.is_dir():
        return
    if (source / "_repo_version.py").exists():
        return  # a built checkout; leave it alone
    shadowed = checkout / "_playwright_src"
    shutil.rmtree(shadowed, ignore_errors=True)
    source.rename(shadowed)
    log("moved the checkout's playwright/ aside so the installed wheel is used")


def prepare(tag: str, *, work: Optional[Path] = None, reuse: bool = True) -> dict:
    work = work or (WORK_DIR / "upstream-suite")
    checkout = fetch(tag, work)
    python = make_venv(checkout, tag, reuse=reuse)
    unshadow(checkout)

    # The plugin travels with the checkout so the suite can be re-run by hand.
    shutil.copy2(CI_DIR / "pw_camoufox_plugin.py", checkout / "pw_camoufox_plugin.py")

    manifest = {
        "tag": tag,
        "checkout": str(checkout),
        "python": str(python),
        "tests": str(checkout / "tests"),
        "test_files": sorted(p.name for p in (checkout / "tests" / "async").glob("test_*.py")),
    }
    write_json(work / "manifest.json", manifest)
    log(f"upstream suite ready: {len(manifest['test_files'])} async test modules at {tag}")
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="playwright-python tag, e.g. v1.62.0")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--fresh", action="store_true", help="rebuild the venv from scratch")
    args = parser.parse_args(argv)
    prepare(args.tag, work=args.work, reuse=not args.fresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
